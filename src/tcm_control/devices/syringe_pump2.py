import re
import time
import importlib
from pathlib import Path

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # Python < 3.11
    tomllib = importlib.import_module("tomli")

import serial

DEFAULT_SPECS_PATH = Path(__file__).resolve().parent.parent / \
    "config" / "config_syringepump2.toml"

STATUS_PATTERN = re.compile(
    r"^\s*(?:(?P<addr>\d{1,2}):)?\s*"
    r"(?P<rate>-?\d+)\s+"
    r"(?P<time>\d+)\s+"
    r"(?P<volume>\d+)\s+"
    r"(?P<flags>[A-Za-z\.]{5,8})\s*$"
)

PROMPT_DESCRIPTIONS = {
    ":": "Pump is idle",
    ">": "Pump is infusing",
    "<": "Pump is withdrawing",
    "*": "Pump stalled",
    "T*": "Target reached",
    ">*": "Infuse limit switch hit",
    "<*": "Withdraw limit switch hit",
    "A*": "Emergency stop active",
}


class SyringePump2:
    def __init__(self, specs: dict):
        self.specs = specs

        serial_cfg = specs["serial"]
        pump_cfg = specs["pump"]

        self.port = serial_cfg["port"]
        self.baudrate = int(serial_cfg.get("baudrate", 9600))
        self.timeout_s = float(serial_cfg.get("timeout_s", 0.2))
        self.pump_address = int(serial_cfg.get("pump_address", 2))
        self.command_delay_s = float(serial_cfg.get("command_delay_s", 0.2))

        self.rate_unit = pump_cfg.get("rate_unit", "m/m")
        self.volume_unit = pump_cfg.get("volume_unit", "m")
        self.status_poll_s = float(pump_cfg.get("status_poll_s", 1.0))
        self.phase_timeout_s = float(pump_cfg.get("phase_timeout_s", 3600))

        self.ser: serial.Serial | None = None

        self.cmd_set_syringe = "syrm"
        self.cmd_set_diameter = "diameter"
        self.cmd_set_gang = "gang"
        self.cmd_set_force = "force"
        self.cmd_set_irate = "irate"
        self.cmd_set_wrate = "wrate"
        self.cmd_set_tvolume = "tvolume"
        self.cmd_set_poll = "poll"
        self.cmd_load_qs = "load qs iw"
        self.cmd_status = "status"
        self.cmd_irun = "irun"
        self.cmd_wrun = "wrun"
        self.cmd_stop = "stop"
        self.cmd_clear_target = "ctvolume"
        self.cmd_clear_volume = "cvolume"
        self.cmd_clear_ivolume = "civolume"
        self.cmd_clear_wvolume = "cwvolume"

    def _log_info(self, msg: str) -> None:
        print(msg)

    def _log_error(self, msg: str) -> None:
        print(f"SyringePump ERROR: {msg}")

    def _sanitize_response_text(self, text: str) -> str:
        return text.replace("\x11", "").replace("\x13", "").replace("\x00", "")

    def _strip_optional_address_prefix(self, line: str) -> tuple[str | None, str]:
        match = re.match(r"^\s*(\d{1,2}):(.*)$", line)
        if not match:
            return None, line.strip()
        return match.group(1), match.group(2).strip()

    def _decode_prompt_text(self, text: str) -> str | None:
        cleaned = self._sanitize_response_text(text).strip()
        if not cleaned:
            return None

        if len(cleaned) > 2 and cleaned[:2].isdigit():
            candidate = cleaned[2:]
        else:
            candidate = cleaned

        return PROMPT_DESCRIPTIONS.get(candidate)

    def _decode_status_flags(self, flags: str) -> tuple[str, bool]:
        info: list[str] = []
        target_reached = False

        if not flags:
            return "No status flags", False

        motor = flags[0]
        if motor == "I":
            info.append("motor running infuse")
        elif motor == "W":
            info.append("motor running withdraw")
        elif motor == "i":
            info.append("motor idle (last dir infuse)")
        elif motor == "w":
            info.append("motor idle (last dir withdraw)")

        if len(flags) > 1:
            if flags[1] == "I":
                info.append("infuse limit switch hit")
            elif flags[1] == "W":
                info.append("withdraw limit switch hit")

        if len(flags) > 2:
            if flags[2] == "S":
                info.append("stall detected")
            elif flags[2] == "A":
                info.append("abnormal stop detected")

        if len(flags) > 3:
            info.append("trigger high" if flags[3] == "T" else "trigger low")

        if len(flags) > 4:
            if flags[4] == "I":
                info.append("direction port: infuse")
            elif flags[4] == "W":
                info.append("direction port: withdraw")

        if len(flags) >= 7:
            if flags[5] == "F":
                info.append("footswitch active")
            target_reached = flags[6] == "T"
        elif len(flags) == 6:
            target_reached = flags[5] == "T"

        if target_reached:
            info.append("target reached")

        return ", ".join(info) if info else "No active flags", target_reached

    def _decode_response(self, text: str) -> tuple[str, bool]:
        text = self._sanitize_response_text(text)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return "(no response)", False

        joined = " | ".join(lines)
        low = joined.lower()

        no_addr_lines = [self._strip_optional_address_prefix(ln)[
            1] for ln in lines]
        no_addr_joined = " | ".join(no_addr_lines)
        no_addr_low = no_addr_joined.lower()

        if "command error:" in low or "command error:" in no_addr_low:
            return f"Pump command error: {no_addr_joined}", False

        if "argument error:" in low or "argument error:" in no_addr_low:
            return f"Pump argument error: {no_addr_joined}", False

        prompt_desc = self._decode_prompt_text(no_addr_lines[-1])
        if prompt_desc:
            done = no_addr_lines[-1].endswith(
                "T*") or no_addr_lines[-1].endswith("A*")
            return prompt_desc, done

        match = STATUS_PATTERN.match(lines[-1])
        if not match:
            _, no_addr_last = self._strip_optional_address_prefix(lines[-1])
            match = STATUS_PATTERN.match(no_addr_last)

        if match:
            rate_fl_s = int(match.group("rate"))
            time_ms = int(match.group("time"))
            volume_fl = int(match.group("volume"))
            flags = match.group("flags")
            flags_text, target_reached = self._decode_status_flags(flags)
            sentence = (
                f"rate={rate_fl_s} fL/s, elapsed={time_ms} ms, "
                f"volume={volume_fl} fL, {flags_text}."
            )
            return sentence, target_reached

        return no_addr_joined, False

    def _send(self, cmd: str, log_errors: bool = True) -> str:
        ser = self.ser
        if ser is None:
            raise RuntimeError("Serial connection is not open.")
        full = cmd + "\r"
        ser.write(full.encode("ascii"))
        ser.flush()
        time.sleep(self.command_delay_s)
        raw = ser.read_all()
        if raw is None:
            response = ""
        else:
            response = raw.decode(errors="ignore").strip()
        sentence, _ = self._decode_response(response)
        low_sentence = sentence.lower()
        if log_errors and ("pump command error:" in low_sentence or "pump argument error:" in low_sentence):
            self._log_error(f"{cmd}: {sentence}")
        return response

    def connect(self) -> None:
        self.ser = serial.Serial(
            self.port, self.baudrate, timeout=self.timeout_s)
        time.sleep(2)
        self._log_info(
            f"Connected to serial device SyringePump at {self.port}")

    def prepare(self, profile: dict) -> None:
        """Prepare pump for direct infuse/withdraw calls."""
        self.connect()
        self.select_pump_address()
        self.clear_previous_command_state()
        self.set_poll_mode("off")
        self.ensure_quickstart_mode()
        self.apply_profile(profile)

    def stop(self) -> None:
        """Stop motor and close serial connection."""
        if self.ser is not None:
            try:
                self._send(self.cmd_stop)
            finally:
                self.disconnect()

    def disconnect(self) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None

    def _format_rate(self, value_ml_min: float) -> str:
        return f"{value_ml_min:g} {self.rate_unit}"

    def _format_volume(self, value_ml: float) -> str:
        return f"{value_ml:g} {self.volume_unit}"

    def set_poll_mode(self, mode: str = "off") -> None:
        self._send(f"{self.cmd_set_poll} {mode}")

    def select_pump_address(self) -> None:
        self._send(f"address {self.pump_address}")

    def ensure_quickstart_mode(self) -> None:
        # Ensure run/time/volume/rate commands are interpreted in Quick Start mode.
        response = self._send(self.cmd_load_qs, log_errors=False)
        sentence, _ = self._decode_response(response)
        low_sentence = sentence.lower()

        # Some firmware revisions do not implement the 'load' command.
        # In that case continue using the current command set.
        if "pump command error:" in low_sentence and "unknown command" in low_sentence:
            return

        if "pump command error:" in low_sentence or "pump argument error:" in low_sentence:
            self._log_error(f"{self.cmd_load_qs}: {sentence}")

    def clear_previous_command_state(self) -> None:
        # Clear stop state, target volume and accumulated run volumes.
        self._send(self.cmd_stop)
        self._send(self.cmd_clear_target)
        self._send(self.cmd_clear_volume)
        self._send(self.cmd_clear_ivolume)
        self._send(self.cmd_clear_wvolume)

    def apply_profile(self, profile: dict) -> None:
        self.select_pump_address()
        self._send(
            f"{self.cmd_set_syringe} {profile['vendor_code']} {profile['volume_ml']:g} ml")
        self._send(f"{self.cmd_set_diameter} {profile['diameter_mm']:g}")
        self._send(f"{self.cmd_set_gang} {profile['gang']}")
        self._send(f"{self.cmd_set_force} {profile['force_percent']}")

    def _wait_until_phase_complete(self, phase_name: str) -> bool:
        started = time.time()

        while True:
            response = self._send(self.cmd_status)
            sentence, target_reached = self._decode_response(response)

            low = response.lower().strip()
            if "t*" in low or target_reached:
                return True

            if low.endswith("a*"):
                self._log_error("Emergency stop reported by pump (A*)")
                return False

            if low.endswith(">*") or low.endswith("<*"):
                self._log_error("Limit switch hit during run")
                return False

            if low.endswith("*"):
                self._log_error("Pump stall reported by prompt '*'")
                return False

            if "command error:" in low or "argument error:" in low:
                self._log_error(
                    f"Pump error response during {phase_name}: {sentence}")
                return False

            if time.time() - started > self.phase_timeout_s:
                self._log_error(f"Safety timeout reached during {phase_name}")
                return False

            time.sleep(self.status_poll_s)

    def _verify_motion_started(self, expected_prompt: str, phase_name: str) -> tuple[bool, str]:
        """Check that phase actually started running right after irun/wrun."""
        response = self._send(self.cmd_status)
        cleaned = self._sanitize_response_text(response).strip()

        # Address-prefixed prompt forms (e.g. 02>) are accepted.
        prompt_ok = cleaned.endswith(
            expected_prompt) or cleaned.endswith(f"{expected_prompt}*")
        if prompt_ok:
            return True, ""

        sentence, _ = self._decode_response(response)
        low_sentence = sentence.lower()
        if "running" in low_sentence and (
            (phase_name == "infusion" and "infuse" in low_sentence)
            or (phase_name == "withdraw" and "withdraw" in low_sentence)
        ):
            return True, sentence

        return False, sentence

    def _start_phase_with_recovery(self, phase_setup_cmds: list[str], run_cmd: str, expected_prompt: str, phase_name: str) -> bool:
        """Clear state, apply phase setup, start run, then retry once silently if needed."""
        # Treat stale target/latch clearing as the normal start path for every phase.
        self.clear_previous_command_state()

        for cmd in phase_setup_cmds:
            self._send(cmd)
        self._send(run_cmd)
        started, sentence = self._verify_motion_started(
            expected_prompt, phase_name)
        if started:
            return True

        # One silent recovery attempt keeps behavior robust without noisy logs.
        self.clear_previous_command_state()
        for cmd in phase_setup_cmds:
            self._send(cmd)
        self._send(run_cmd)
        started_retry, sentence_retry = self._verify_motion_started(
            expected_prompt, phase_name)
        if started_retry:
            return True

        self._log_error(
            f"{phase_name} did not start. Last status: {sentence_retry or sentence}")
        return False

    def infuse(self, volume_ml: float, rate_ml_min: float, wait_for_completion: bool = True) -> bool:
        if wait_for_completion:
            self._log_info(
                f"SyringePump infusing at {rate_ml_min:g} mL/min to {volume_ml:g} mL target")
        else:
            self._log_info(
                f"SyringePump infusing at {rate_ml_min:g} mL/min")
        phase_setup_cmds = [
            f"{self.cmd_set_irate} {self._format_rate(rate_ml_min)}",
            f"{self.cmd_set_tvolume} {self._format_volume(volume_ml)}",
        ]
        if not self._start_phase_with_recovery(phase_setup_cmds, self.cmd_irun, ">", "infusion"):
            return False
        if wait_for_completion:
            return self._wait_until_phase_complete("infusion")
        return True

    def withdraw(self, volume_ml: float, rate_ml_min: float, wait_for_completion: bool = True) -> bool:
        if wait_for_completion:
            self._log_info(
                f"SyringePump withdrawing at {rate_ml_min:g} mL/min to {volume_ml:g} mL target")
        else:
            self._log_info(
                f"SyringePump withdrawing at {rate_ml_min:g} mL/min")
        phase_setup_cmds = [
            f"{self.cmd_set_wrate} {self._format_rate(rate_ml_min)}",
            f"{self.cmd_set_tvolume} {self._format_volume(volume_ml)}",
        ]
        if not self._start_phase_with_recovery(phase_setup_cmds, self.cmd_wrun, "<", "withdraw"):
            return False
        if wait_for_completion:
            return self._wait_until_phase_complete("withdraw")
        return True

    def run_protocol(self, steps: list[dict]) -> None:
        if not steps:
            self._log_info("SyringePump protocol has no steps")
            return

        for idx, step in enumerate(steps, start=1):
            action = str(step["action"]).strip().lower()
            volume_ml = float(step["volume_ml"])
            rate_ml_min = float(step["rate_ml_min"])
            wait_for_completion = bool(step.get("wait_for_completion", True))
            settle_s = float(step.get("settle_s", 0.0))

            if action == "infuse":
                ok = self.infuse(volume_ml, rate_ml_min,
                                 wait_for_completion=wait_for_completion)
            elif action == "withdraw":
                ok = self.withdraw(volume_ml, rate_ml_min,
                                   wait_for_completion=wait_for_completion)
            else:
                raise ValueError(f"Unknown protocol action: {action}")

            if not ok:
                raise RuntimeError(
                    f"Protocol aborted at step {idx} ({action})")

            if settle_s > 0:
                time.sleep(settle_s)


def load_specs(specs_path: Path) -> dict:
    with specs_path.open("rb") as f:
        return tomllib.load(f)


def get_active_profile(specs: dict) -> dict:
    active_profile_key = specs.get("serial", []).get('active_profile')
    profiles = specs["profiles"]
    if active_profile_key not in profiles:
        raise KeyError(
            f"active_profile '{active_profile_key}' was not found in profiles")
    return profiles[active_profile_key]


def get_first_action_step(specs: dict, action_name: str) -> dict | None:
    steps = specs.get(action_name, [])
    if not steps:
        return None
    return steps[0]


def main(specs_path: Path = DEFAULT_SPECS_PATH) -> None:
    specs = load_specs(specs_path)
    profile = get_active_profile(specs)
    infuse_step = get_first_action_step(specs, "infuse")
    withdraw_step = get_first_action_step(specs, "withdraw")

    pump = SyringePump2(specs)
    try:
        pump.prepare(profile)

        if infuse_step is not None:
            pump.infuse(
                volume_ml=infuse_step["volume_ml"],
                rate_ml_min=infuse_step["rate_ml_min"]
            )

        if withdraw_step is not None:
            pump.withdraw(
                volume_ml=withdraw_step["volume_ml"],
                rate_ml_min=withdraw_step["rate_ml_min"]
            )

        if infuse_step is None and withdraw_step is None:
            pump._log_info("SyringePump config has no infuse/withdraw steps")
    except Exception as exc:
        pump._log_error(str(exc))
        raise
    finally:
        pump.stop()


if __name__ == "__main__":
    main()

import re
import time
import importlib
from collections.abc import Callable
from pathlib import Path

try:
    tomllib = importlib.import_module("tomllib")
except ModuleNotFoundError:  # Python < 3.11
    tomllib = importlib.import_module("tomli")

from .base_serial import PoFSerialDevice

DEFAULT_SPECS_PATH = Path(__file__).resolve().parent.parent / \
    "config" / "config_layer.toml"
DEFAULT_SYRINGES_PATH = Path(__file__).resolve().parent / \
    "lookup_tables" / "syringes.toml"

RATE_UNIT = "m/m"
VOLUME_UNIT = "m"
STATUS_POLL_S = 1.0
PHASE_TIMEOUT_S = 3600.0
COMMAND_DELAY_S = 0.2
CONNECTION_SETTLE_S = 2.0

CMD_SET_SYRINGE = "syrm"
CMD_SET_DIAMETER = "diameter"
CMD_SET_GANG = "gang"
CMD_SET_FORCE = "force"
CMD_SET_IRATE = "irate"
CMD_SET_WRATE = "wrate"
CMD_SET_TVOLUME = "tvolume"
CMD_SET_POLL = "poll"
CMD_LOAD_QS = "load qs iw"
CMD_STATUS = "status"
CMD_IRUN = "irun"
CMD_WRUN = "wrun"
CMD_STOP = "stop"
CMD_CLEAR_TARGET = "ctvolume"
CMD_CLEAR_VOLUME = "cvolume"
CMD_CLEAR_IVOLUME = "civolume"
CMD_CLEAR_WVOLUME = "cwvolume"

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


class SyringePump(PoFSerialDevice):
    def __init__(
        self,
        syringe_vendor_code,
        syringe_volume_mL,
        syringe_diameter_mm,
        syringe_gang,
        syringe_force_percent,
        *,
        name: str = "SyringePump",
        long_name: str = "Harvard PHD Ultra",
        baudrate: int = 9600,
        timeout_s: float = 0.2,
        debug: bool = False,
    ) -> None:
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.pump_address = 0
        self.command_delay_s = COMMAND_DELAY_S
        self.rate_unit = RATE_UNIT
        self.volume_unit = VOLUME_UNIT
        self.status_poll_s = STATUS_POLL_S
        self.phase_timeout_s = PHASE_TIMEOUT_S
        self.syringe_vendor_code = syringe_vendor_code
        self.syringe_volume_mL = syringe_volume_mL
        self.syringe_diameter_mm = syringe_diameter_mm
        self.syringe_gang = syringe_gang
        self.syringe_force_percent = syringe_force_percent

        super().__init__(
            name=name,
            long_name=long_name,
            expected_id="PHD Ultra",
            baudrate=baudrate,
            timeout=timeout_s,
            debug=debug,
        )
        self.port = self.ser.port
        try:
            self.prepare()
            self.apply_profile()
        except Exception:
            self.disconnect()
            raise

    def infuse(self, volume_ml: float, rate_ml_min: float, wait_for_completion: bool = True, *, update: Callable[[], None] | None = None) -> bool:
        return self._run_phase(
            action_verb="infusing",
            phase_name="infusion",
            volume_ml=volume_ml,
            rate_ml_min=rate_ml_min,
            rate_cmd=CMD_SET_IRATE,
            run_cmd=CMD_IRUN,
            expected_prompt=">",
            wait_for_completion=wait_for_completion,
            update=update,
        )

    def withdraw(self, volume_ml: float, rate_ml_min: float, wait_for_completion: bool = True, *, update: Callable[[], None] | None = None) -> bool:
        return self._run_phase(
            action_verb="withdrawing",
            phase_name="withdraw",
            volume_ml=volume_ml,
            rate_ml_min=rate_ml_min,
            rate_cmd=CMD_SET_WRATE,
            run_cmd=CMD_WRUN,
            expected_prompt="<",
            wait_for_completion=wait_for_completion,
            update=update,
        )

    def _log_info(self, msg: str) -> None:
        print(msg)

    def _log_error(self, msg: str) -> None:
        print(f"SyringePump ERROR: {msg}")

    def _sanitize_response_text(self, text: str) -> str:
        return text.replace("\x11", "").replace("\x13", "").replace("\x00", "")

    def _is_error_text(self, text: str) -> bool:
        low = text.lower()
        return "pump command error:" in low or "pump argument error:" in low

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
        if log_errors and self._is_error_text(sentence):
            self._log_error(f"{cmd}: {sentence}")
        return response

    def _identify_for_connection(self) -> tuple[str, None]:
        time.sleep(CONNECTION_SETTLE_S)
        self.ser.read_all()
        response = self._send("ver", log_errors=False)
        for line in self._sanitize_response_text(response).splitlines():
            _, line = self._strip_optional_address_prefix(line)
            if re.fullmatch(r"PHD Ultra \d+\.\d+\.\d+", line):
                return "PHD Ultra", None
        return "", None

    def connect(self) -> None:
        if not self.is_alive:
            self._connect()
            self.port = self.ser.port

    def prepare(self) -> None:
        """Prepare pump for direct infuse/withdraw calls."""
        self.connect()
        self.select_pump_address()
        self.clear_previous_command_state()
        self.set_poll_mode("off")
        self.ensure_quickstart_mode()

    def stop(self) -> None:
        """Stop motor and close serial connection."""
        if self.ser is not None:
            try:
                self._send(CMD_STOP)
            finally:
                self.disconnect()

    def disconnect(self) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None
            self.is_alive = False

    def _format_rate(self, value_ml_min: float) -> str:
        return f"{value_ml_min:g} {self.rate_unit}"

    def _format_volume(self, value_ml: float) -> str:
        return f"{value_ml:g} {self.volume_unit}"

    def set_poll_mode(self, mode: str = "off") -> None:
        self._send(f"{CMD_SET_POLL} {mode}")

    def select_pump_address(self) -> None:
        """Verify the standalone pump address without changing its setting."""
        response = self._sanitize_response_text(self._send("address"))
        if not re.search(r"(?im)^\s*(?:\d{1,2}:)?\s*Pump address is 0\s*$", response):
            raise RuntimeError(f"Expected pump address 0, got: {response!r}")

    def ensure_quickstart_mode(self) -> None:
        # Ensure run/time/volume/rate commands are interpreted in Quick Start mode.
        response = self._send(CMD_LOAD_QS, log_errors=False)
        sentence, _ = self._decode_response(response)
        low_sentence = sentence.lower()

        # Some firmware revisions do not implement the 'load' command.
        # In that case continue using the current command set.
        if "pump command error:" in low_sentence and "unknown command" in low_sentence:
            return

        if self._is_error_text(sentence):
            self._log_error(f"{CMD_LOAD_QS}: {sentence}")

    def _run_phase(
        self,
        *,
        action_verb: str,
        phase_name: str,
        volume_ml: float,
        rate_ml_min: float,
        rate_cmd: str,
        run_cmd: str,
        expected_prompt: str,
        wait_for_completion: bool,
        update: Callable[[], None] | None = None,
    ) -> bool:
        if wait_for_completion:
            self._log_info(
                f"SyringePump {action_verb} at {rate_ml_min:g} mL/min to {volume_ml:g} mL target"
            )
        else:
            self._log_info(
                f"SyringePump {action_verb} at {rate_ml_min:g} mL/min")

        # Pump does not like zero volume targets, so use a tiny volume instead.
        if volume_ml == 0.0:
            volume_ml = 0.001

        phase_setup_cmds = [
            f"{rate_cmd} {self._format_rate(rate_ml_min)}",
            f"{CMD_SET_TVOLUME} {self._format_volume(volume_ml)}",
        ]
        if not self._start_phase_with_recovery(phase_setup_cmds, run_cmd, expected_prompt, phase_name):
            return False
        if wait_for_completion:
            return self._wait_until_phase_complete(phase_name, update=update)
        return True

    def clear_previous_command_state(self) -> None:
        # Clear stop state, target volume and accumulated run volumes.
        self._send(CMD_STOP)
        self._send(CMD_CLEAR_TARGET)
        self._send(CMD_CLEAR_VOLUME)
        self._send(CMD_CLEAR_IVOLUME)
        self._send(CMD_CLEAR_WVOLUME)

    def apply_profile(self) -> None:
        self.select_pump_address()
        self._send(
            f"{CMD_SET_SYRINGE} {self.syringe_vendor_code} {self.syringe_volume_mL:g} ml")
        self._send(f"{CMD_SET_DIAMETER} {self.syringe_diameter_mm:g}")
        self._send(f"{CMD_SET_GANG} {self.syringe_gang}")
        self._send(f"{CMD_SET_FORCE} {self.syringe_force_percent:g}")

    def _wait_until_phase_complete(self, phase_name: str, update: Callable[[], None] | None = None) -> bool:
        started = time.time()

        while True:
            response = self._send(CMD_STATUS)
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

            self._wait_with_updates(self.status_poll_s, update)

    @staticmethod
    def _wait_with_updates(duration_s: float, update: Callable[[], None] | None) -> None:
        if update is None:
            time.sleep(duration_s)
            return
        end = time.monotonic() + duration_s
        while time.monotonic() < end:
            update()
            remaining = end - time.monotonic()
            if remaining > 0:
                time.sleep(min(0.1, remaining))

    def _verify_motion_started(self, expected_prompt: str, phase_name: str) -> tuple[bool, str]:
        """Check that phase actually started running right after irun/wrun."""
        response = self._send(CMD_STATUS)
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

    def make_layer(self, infuse_volume_ml: float, infuse_rate_ml_min: float, withdraw_volume_ml: float, withdraw_rate_ml_min: float, settling_time_s: float, *, update: Callable[[], None] | None = None) -> None:
        """Create a thin film layer using the syringe pump."""
        try:
            # Infuse fluid to create the layer

            self.infuse(
                volume_ml=infuse_volume_ml,
                rate_ml_min=infuse_rate_ml_min,
                update=update,
            )

            # Allow the pump system and fluid to relax
            self._wait_with_updates(settling_time_s, update)

            # Partially withdraw to create a thin film layer
            self.withdraw(
                volume_ml=withdraw_volume_ml,
                rate_ml_min=withdraw_rate_ml_min,
                update=update,
            )
        except Exception as exc:
            self._log_error(str(exc))
            raise

    def clean_tubes(self, volume_ml_layer: float, rate_ml_min_layer: float, volume_ml_repetition: float | None, rate_ml_min_repetition: float | None, repetitions: int) -> None:
        """Clean the tubes by performing repeated infuse/withdraw cycles."""
        try:
            if repetitions > 0 and (volume_ml_repetition is None or rate_ml_min_repetition is None):
                raise ValueError("Repetition volume and rate are required when cleaning repetitions are enabled.")

            # Initial infusion to create fluid layer
            self.infuse(
                volume_ml=volume_ml_layer,
                rate_ml_min=rate_ml_min_layer
            )

            # Seesaw fluid back and forth through tubes to clean them
            if repetitions > 0:
                assert volume_ml_repetition is not None and rate_ml_min_repetition is not None
                for _ in range(repetitions):
                    self.withdraw(
                        volume_ml=volume_ml_repetition,
                        rate_ml_min=rate_ml_min_repetition
                    )
                    self.infuse(
                        volume_ml=volume_ml_repetition,
                        rate_ml_min=rate_ml_min_repetition
                    )
            else:
                self._log_info("SyringePump config has no clean_tube steps")

        except Exception as exc:
            self._log_error(str(exc))
            raise


def main(specs_path: Path = DEFAULT_SPECS_PATH) -> None:
    config: dict = {}
    if specs_path.exists():
        config = tomllib.load(specs_path.open("rb"))

    syringe_inputs = config["devices"]["pump"]["syringe"]
    layer_inputs = config["devices"]["pump"]["layer"]
    clean_tube = config["devices"]["pump"]["clean_tube"]

    pump = SyringePump(syringe_inputs["syringe_vendor_code"],
                       syringe_inputs["syringe_volume_mL"],
                       syringe_inputs["syringe_diameter_mm"],
                       syringe_inputs["syringe_gang"],
                       syringe_inputs["syringe_force_percent"])

    pump.make_layer(infuse_volume_ml=layer_inputs["infuse_volume_ml"],
                    infuse_rate_ml_min=layer_inputs["infuse_rate_ml_min"],
                    withdraw_volume_ml=layer_inputs["withdraw_volume_ml"],
                    withdraw_rate_ml_min=layer_inputs["withdraw_rate_ml_min"],
                    settling_time_s=layer_inputs["film_settling_time_s"])

    pump = SyringePump(syringe_inputs["syringe_vendor_code"],
                       syringe_inputs["syringe_volume_mL"],
                       syringe_inputs["syringe_diameter_mm"],
                       syringe_inputs["syringe_gang"],
                       syringe_inputs["syringe_force_percent"])

    pump.clean_tubes(volume_ml_layer=clean_tube["volume_ml_layer"],
                     rate_ml_min_layer=clean_tube["rate_ml_min_layer"],
                     volume_ml_repetition=clean_tube["volume_ml_repetition"],
                     rate_ml_min_repetition=clean_tube["rate_ml_min_repetition"],
                     repetitions=clean_tube["repetitions"])


if __name__ == "__main__":
    main()

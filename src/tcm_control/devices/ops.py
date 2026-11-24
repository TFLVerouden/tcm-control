"""Control and record a TSI 3330 optical particle sizer over TCP."""

import csv
import math
import socket
import threading
import time
from pathlib import Path

SAMPLE_INTERVAL_S = 1
MAX_RECORDING_S = 60
POLL_INTERVAL_S = 0.05
START_TIMEOUT_S = 30.0
NUMBER_OF_CHANNELS = 16
START_TIME = "00:00"
START_DATE = "01/01/2026"
NUMBER_OF_SETS = 1
REPEAT_INTERVAL = "0:00:01"
USE_START_TIME = 0
USE_START_DATE = 0
LOGGING_ENABLED = 1
LOG_TO_SINGLE_FILE = 1
SURVEY_MODE = 0
KEEP_PUMP_RUNNING = 1
ALARM_VISIBLE = 1
ALARM_AUDIBLE = 0
ALARM_RELAY = 0
ALARM_MEASUREMENT_DN = 1
USER_CALIBRATION_ENABLED = 0
DEAD_TIME_CORRECTION_ENABLED = 1
DENSITY = 1.0
REFRACTIVE_INDEX_REAL = 1.5
REFRACTIVE_INDEX_IMAGINARY = 0.0
SHAPE_CORRECTION_FACTOR = 0.0
FLOW_CALIBRATION_FACTOR = 1.0
EXTERNAL_FLOW_CONTROL = 0


def validate_bin_boundaries(values: object) -> list[float]:
    if not isinstance(values, list) or len(values) != 17:
        raise ValueError("OPS bin_boundaries_um must contain 17 boundaries for 16 channels.")
    try:
        boundaries = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise ValueError("OPS bin boundaries must be numeric.") from exc
    if (not all(math.isfinite(value) and 0.3 <= value <= 10.0 for value in boundaries)
            or any(upper < lower * 1.05 for lower, upper in zip(boundaries, boundaries[1:]))):
        raise ValueError("OPS boundaries must be within 0.3-10 um and at least 5% apart.")
    return boundaries


class OpticalParticleSizer:
    def __init__(
        self,
        bin_boundaries_um: list[float],
        alarm_threshold: float,
        *,
        ip: str = "192.168.1.50",
        port: int = 3602,
        timeout_s: float = 5.0,
        idle_gap_s: float = 0.25,
    ) -> None:
        self.ip = ip
        self.port = port
        self.timeout_s = timeout_s
        self.idle_gap_s = idle_gap_s
        self.bin_boundaries_um = validate_bin_boundaries(bin_boundaries_um)
        if not math.isfinite(alarm_threshold) or not 0 <= alarm_threshold <= 10000:
            raise ValueError("OPS alarm_threshold must be between 0 and 10000 particles/cm3.")
        self.alarm_threshold = alarm_threshold
        self._socket: socket.socket | None = None
        self._record_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._record_error: Exception | None = None
        self._record_path: Path | None = None
        self._stop_deadline: float | None = None
        self._started_at = 0.0

        try:
            self._socket = socket.create_connection((ip, port), timeout_s)
            self.model = self._send("RDMN")
            if self.model.strip() != "3330":
                raise RuntimeError(f"Unexpected OPS model: {self.model!r}")
            self.serial_number = self._send("RDSN")
            self.firmware_version = self._send("RDBS")
            self.calibration_info = self._send("RSCALDATE")
            self._configure()
            self.instrument_settings = {
                "channels": self._send("RMODECHSETUP"),
                "logging": self._send("RMODELOG"),
                "alarm": self._send("RMODEALARM"),
                "user_calibration": self._send("RMODEUSERCAL"),
                "flow_calibration": self._send("RMODEFLOWCAL"),
            }
        except Exception:
            self.close()
            raise
        print(f"Connected to OpticalParticleSizer at {ip}:{port}")

    def _send(self, command: str) -> str:
        if self._socket is None:
            raise RuntimeError("OpticalParticleSizer is not connected.")
        self._socket.sendall((command + "\r").encode("ascii"))
        self._socket.settimeout(self.timeout_s)
        try:
            first = self._socket.recv(4096)
            if not first:
                raise RuntimeError("OpticalParticleSizer connection closed.")
            chunks = [first]
            self._socket.settimeout(self.idle_gap_s)
            while True:
                try:
                    chunk = self._socket.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    raise RuntimeError("OpticalParticleSizer connection closed.")
                chunks.append(chunk)
        except socket.timeout as exc:
            raise RuntimeError(f"OpticalParticleSizer timed out on {command!r}") from exc
        finally:
            self._socket.settimeout(self.timeout_s)
        reply = b"".join(chunks).decode("ascii").strip()
        if reply.upper().startswith(("ERROR", "FAIL")):
            raise RuntimeError(f"OpticalParticleSizer rejected {command!r}: {reply}")
        return reply

    def _write(self, command: str) -> None:
        reply = self._send(command)
        if reply.upper() != "OK":
            raise RuntimeError(f"OpticalParticleSizer rejected {command!r}: {reply}")

    def _configure(self) -> None:
        boundaries = ",".join(f"{value:g}" for value in self.bin_boundaries_um)
        self._write(f"WMODECHSETUP {NUMBER_OF_CHANNELS},{boundaries}")
        self._write(
            f"WMODELOG {START_TIME},{START_DATE},0:00:{SAMPLE_INTERVAL_S},"
            f"{MAX_RECORDING_S},{NUMBER_OF_SETS},{REPEAT_INTERVAL},"
            f"{USE_START_TIME},{USE_START_DATE},{LOGGING_ENABLED},"
            f"{LOG_TO_SINGLE_FILE},{SURVEY_MODE},{KEEP_PUMP_RUNNING}"
        )
        self._write(
            f"WMODEALARM {ALARM_VISIBLE},{ALARM_AUDIBLE},{ALARM_RELAY},"
            f"{ALARM_MEASUREMENT_DN},{self.alarm_threshold:g}"
        )
        self._write(
            f"WMODEUSERCAL {USER_CALIBRATION_ENABLED},{DEAD_TIME_CORRECTION_ENABLED},"
            f"{DENSITY:g},{REFRACTIVE_INDEX_REAL:g},{REFRACTIVE_INDEX_IMAGINARY:g},"
            f"{SHAPE_CORRECTION_FACTOR:g}"
        )
        self._write(f"WMODEFLOWCAL {FLOW_CALIBRATION_FACTOR:g},{EXTERNAL_FLOW_CONTROL}")
        self._write("MUPDATE")
        self._wait_for_status("Idle")

    def _wait_for_status(self, expected: str) -> None:
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            status = self._send("MSTATUS")
            if status.casefold() == expected.casefold():
                return
            if "error" in status.casefold():
                raise RuntimeError(f"OpticalParticleSizer status: {status}")
            time.sleep(0.1)
        raise TimeoutError(f"OpticalParticleSizer did not reach {expected!r}; last status: {status!r}")

    def start_recording(self, output_dir: str | Path) -> None:
        if self._record_thread is not None:
            raise RuntimeError("OpticalParticleSizer recording has not been collected.")
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self._record_path = output_dir / "ops.csv"
        self._record_error = None
        self._stop_deadline = None
        self._stop_event.clear()
        self._wait_for_status("Idle")
        self._started_at = time.monotonic()
        try:
            self._write("MSTART")
            self._wait_for_status("Running")
        except Exception as start_error:
            try:
                self._write("MSTOP")
            except Exception as stop_error:
                raise ExceptionGroup(
                    "OpticalParticleSizer start and stop failed.",
                    [start_error, stop_error],
                ) from start_error
            raise
        self._record_thread = threading.Thread(target=self._record, name="ops-recording")
        try:
            self._record_thread.start()
        except Exception:
            self._record_thread = None
            self._write("MSTOP")
            raise
        print("OpticalParticleSizer recording started")

    def _record(self) -> None:
        try:
            assert self._record_path is not None
            with self._record_path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(
                    ["elapsed_s", "sample_second_s", "valid_sample"]
                    + [f"bin_{i}_count" for i in range(1, 17)]
                    + ["above_bin_16_count", "flow_lpm", "sheath_flow_lpm",
                       "laser_current_ma", "laser_scatter_v", "flow_temperature_c",
                       "unit_temperature_c", "humidity_percent", "pressure_kpa",
                       "system_error", "measurement_alarm"]
                )
                last_second = None
                while not self._stop_event.is_set():
                    if self._stop_deadline is not None and time.monotonic() >= self._stop_deadline:
                        break
                    if time.monotonic() - self._started_at >= MAX_RECORDING_S:
                        raise TimeoutError(
                            f"OpticalParticleSizer recording reached the {MAX_RECORDING_S}-second limit."
                        )
                    response = self._send("RMLOGGEDBINS").split("\r")
                    if len(response) < 2:
                        raise RuntimeError("Invalid OpticalParticleSizer bin response.")
                    fields = [part.strip() for part in response[0].split(",")]
                    bins = [part.strip() for part in response[1].split(",") if part.strip()]
                    if len(fields) < 3 or len(bins) != 17:
                        raise RuntimeError(f"Invalid OpticalParticleSizer bin response: {response!r}")
                    second = int(fields[0])
                    if last_second is None and second > SAMPLE_INTERVAL_S:
                        raise RuntimeError(f"OpticalParticleSizer missed initial samples before {second} s.")
                    if last_second is not None and second < last_second:
                        raise RuntimeError("OpticalParticleSizer sample time went backwards.")
                    if last_second is not None and second > last_second + SAMPLE_INTERVAL_S:
                        raise RuntimeError(f"OpticalParticleSizer missed samples after {last_second} s.")
                    if second != last_second:
                        unit = [part.strip() for part in self._send("RMUNITMEAS").split(",")]
                        messages = [part.strip() for part in self._send("RMMESSAGES").split(",")]
                        if len(unit) < 8 or len(messages) < 3:
                            raise RuntimeError("Invalid OpticalParticleSizer unit or message response.")
                        writer.writerow([second, fields[1], fields[2], *bins, *unit[:8], messages[1], messages[2]])
                        file.flush()
                        last_second = second
                    else:
                        self._stop_event.wait(POLL_INTERVAL_S)
                if last_second is None:
                    raise RuntimeError("OpticalParticleSizer recorded no samples.")
        except Exception as exc:
            self._record_error = exc
            self._stop_event.set()
        finally:
            try:
                self._write("MSTOP")
            except Exception as exc:
                if self._record_error is not None:
                    self._record_error = ExceptionGroup(
                        "OpticalParticleSizer recording and stop failed.",
                        [self._record_error, exc],
                    )
                else:
                    self._record_error = exc

    def check_recording(self) -> None:
        if self._record_error is not None:
            raise RuntimeError("OpticalParticleSizer recording failed.") from self._record_error

    def finish_after(self, duration_s: float) -> None:
        if self._record_thread is None:
            raise RuntimeError("OpticalParticleSizer is not recording.")
        if not math.isfinite(duration_s) or duration_s < 0:
            raise ValueError("OPS post-run duration must be finite and non-negative.")
        self.check_recording()
        self._stop_deadline = time.monotonic() + duration_s

    def collect_recording(self) -> Path:
        if self._record_thread is None or self._record_path is None:
            raise RuntimeError("OpticalParticleSizer is not recording.")
        if self._stop_deadline is None and not self._stop_event.is_set():
            raise RuntimeError("OpticalParticleSizer stop has not been scheduled.")
        self._record_thread.join()
        self._record_thread = None
        self.check_recording()
        print(f"OpticalParticleSizer data saved to {self._record_path}")
        return self._record_path

    def stop_recording(self) -> Path:
        self._stop_event.set()
        return self.collect_recording()

    def stop_if_recording(self) -> None:
        if self._record_thread is not None:
            self.stop_recording()

    def metadata(self) -> dict:
        return {
            "model": self.model,
            "serial_number": self.serial_number,
            "firmware_version": self.firmware_version,
            "calibration_info": self.calibration_info,
            "connection": {"ip": self.ip, "port": self.port, "timeout_s": self.timeout_s},
            "instrument_settings": self.instrument_settings,
            "settings": {
                "bin_boundaries_um": self.bin_boundaries_um,
                "alarm_threshold": self.alarm_threshold,
                "sample_interval_s": SAMPLE_INTERVAL_S,
                "max_recording_s": MAX_RECORDING_S,
                "user_calibration_enabled": bool(USER_CALIBRATION_ENABLED),
                "dead_time_correction_enabled": bool(DEAD_TIME_CORRECTION_ENABLED),
                "density": DENSITY,
                "refractive_index_real": REFRACTIVE_INDEX_REAL,
                "refractive_index_imaginary": REFRACTIVE_INDEX_IMAGINARY,
                "shape_correction_factor": SHAPE_CORRECTION_FACTOR,
                "flow_calibration_factor": FLOW_CALIBRATION_FACTOR,
            },
        }

    def close(self) -> None:
        try:
            if self._record_thread is not None:
                self.stop_recording()
        finally:
            if self._socket is not None:
                self._socket.close()
                self._socket = None

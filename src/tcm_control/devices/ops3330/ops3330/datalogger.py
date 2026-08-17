"""
Poll the OPS during a measurement and save the results to a CSV file.

The OPS protocol has no "download the file the instrument saved" command --
on the instrument itself, data is written to a USB flash drive plugged into
the unit, not handed back over the command socket. To get data onto the
controlling PC, this module instead starts a measurement, polls the
instrument every second, detects each newly-completed logged sample (via
the "valid sample" flag in RMLOGGEDBINS), and writes a CSV modeled on the
column layout described in Appendix B of the manual.
"""

from __future__ import annotations

import csv
import logging
import time
import datetime
from pathlib import Path
from typing import Optional

from .client import OPSClient, OPSError

logger = logging.getLogger("ops3330")


def _parse_csv_ints_floats(s: str) -> list[str]:
    return [p.strip() for p in s.replace("\r", ",").split(",") if p.strip() != ""]

def _time_test_length(test_length: int) -> str:
    """Convert test length in seconds to a string in the format D:H:M:S."""
    days, remainder = divmod(test_length, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}:{hours}:{minutes}:{seconds}"

def _time_sample_interval(sample_interval: int) -> str:
    """Convert sample interval in seconds to a string in the format H:M:S."""
    hours, remainder = divmod(sample_interval, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes}:{seconds}"

def _update_errors_row(out_path: Path, error_message: str) -> None:
    """Update the existing CSV metadata row named 'Errors'."""
    with out_path.open("r", newline="") as f:
        rows = list(csv.reader(f))

    for row in rows:
        if row and row[0] == "Errors":
            if len(row) == 1:
                row.append(error_message)
            elif row[1]:
                row[1] = f"{row[1]}; {error_message}"
            else:
                row[1] = error_message
            break
    else:
        return

    with out_path.open("w", newline="") as f:
        csv.writer(f).writerows(rows)


def record_measurement(
    client: OPSClient,
    out_path: str | Path,
    max_samples: Optional[int] = None,
    max_duration_s: Optional[float] = None,
    poll_interval_s: float = 1.0,
    start: bool = True,
    stop_when_done: bool = True,
) -> Path:
    """
    Run (or attach to) a measurement and save logged samples to `out_path`.

    max_samples: stop after this many logged samples (None = no limit,
        rely on max_duration_s or the instrument's own logging setup).
    max_duration_s: stop after this many seconds have elapsed (None = no
        limit).
    poll_interval_s: how often to poll RMLOGGEDBINS/RMLOGGEDMEAS for a new
        sample.
    start: call MSTART before polling (set False if you already started
        the measurement yourself).
    stop_when_done: call MSTOP once the loop finishes.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    model = client.read_model_number()
    serial = client.read_serial_number()
    firmware = client.read_firmware_version()
    cal_date = client.read_calibration_date()
    ch_setup = client.read_channel_setup()
    log_setup = client.read_log_setup()
    alarm_setup = client.read_alarm_setup()
    user_cal_setup = client.read_user_cal()
    flow_cal_setup = client.read_flow_cal()
    n_channels = int(_parse_csv_ints_floats(ch_setup)[0])

    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Instrument Name", "Optical Particle Sizer"])
        writer.writerow(["Model Number", model])
        writer.writerow(["Serial Number", serial])
        writer.writerow(["Firmware Version", firmware])
        writer.writerow(["Calibration Date", cal_date[0]])

        writer.writerow(["ProtocolName_Number", "TEST_124"])
        writer.writerow(["TestStartTime", datetime.datetime.now().strftime("%H:%M:%S")])
        writer.writerow(["TestStartDate", datetime.datetime.now().strftime("%Y/%m/%d")])
        writer.writerow(["TestLength [D:H:M:S]", _time_test_length(max_duration_s)])
        writer.writerow(["Sample Interval [H:M:S]", _time_sample_interval(poll_interval_s)])
        writer.writerow(["Number Channels Enabled", n_channels])
        for i in range(0, n_channels + 1):
            writer.writerow([f"Bin {i + 1} Cut Point (um)", _parse_csv_ints_floats(ch_setup)[i + 1]])
        writer.writerow(["Alarm threshold [#/cm3]", _parse_csv_ints_floats(alarm_setup)[4]])
        writer.writerow(["Density [g/cm3]", _parse_csv_ints_floats(user_cal_setup)[2]])
        writer.writerow(["Refractive Index", _parse_csv_ints_floats(user_cal_setup)[3] + "-" + _parse_csv_ints_floats(user_cal_setup)[4] + "j"])
        writer.writerow(["Shape Correction Factor", _parse_csv_ints_floats(user_cal_setup)[5]])
        writer.writerow(["FlowCal", _parse_csv_ints_floats(flow_cal_setup)[0]])
        writer.writerow(["Deadtime Correction Factor", _parse_csv_ints_floats(user_cal_setup)[1]])

        # Placeholder error row; it will be updated after the measurement finishes.
        writer.writerow(["Errors", ""])
        writer.writerow(["Number of Samples", _parse_csv_ints_floats(log_setup)[3]])
        writer.writerow(["", ""])

        header = (
            ["Elapsed Time [s]"]
            + [f"Bin {i + 1}" for i in range(n_channels + 1)]
            + ["Deadtime (s)", "Temperature (C)", "Humidity (%)", "Ambient Pressure (kPa)"]
            + ["Alarms", "Errors"]
        )
        writer.writerow(header)

        if start:
            client.start_measurement()

        t0 = time.monotonic()
        n_saved = 0
        last_valid_flag: Optional[str] = None
        collected_errors: list[str] = []

        try:
            while True:
                if max_duration_s is not None and (time.monotonic() - t0) >= max_duration_s:
                    logger.info("Reached max_duration_s, stopping.")
                    break
                if max_samples is not None and n_saved >= max_samples:
                    logger.info("Reached max_samples, stopping.")
                    break
                
                try:
                    logged = client.read_logged_bins()
                except OPSError as e:
                    logger.warning("read_logged_bins failed: %s", e)
                    time.sleep(poll_interval_s)
                    continue

                lines = logged.split("\r")
                meta = _parse_csv_ints_floats(lines[0]) if lines else []
                valid_flag = meta[0] if len(meta) > 2 else None

                if valid_flag is not None and valid_flag != last_valid_flag:
                    last_valid_flag = valid_flag
                    elapsed = meta[0] if len(meta) > 1 else str(round(time.monotonic() - t0, 1))
                    bins = _parse_csv_ints_floats(lines[1]) if len(lines) > 1 else []

                    try:
                        unit_meas = _parse_csv_ints_floats(client.read_unit_measurements())
                    except OPSError:
                        unit_meas = []
                    deadtime = unit_meas[3] if len(unit_meas) > 3 else ""
                    temp = unit_meas[4] if len(unit_meas) > 4 else ""
                    humidity = unit_meas[6] if len(unit_meas) > 6 else ""
                    pressure = unit_meas[7] if len(unit_meas) > 7 else ""
                    errors = unit_meas[8] if len(unit_meas) > 8 else ""
                    if errors == None:
                        errors = ""

                    try:
                        messages = _parse_csv_ints_floats(client.read_messages())
                    except OPSError:
                        messages = []
                    alarm_flag = messages[2] if len(messages) > 2 else ""

                    row = (
                        [elapsed]
                        + bins
                        + [deadtime, temp, humidity, pressure, alarm_flag, errors]
                    )

                    # Write errors to the error row if any errors are present
                    if errors:
                        collected_errors.append(errors)

                    writer.writerow(row)
                    f.flush()
                    n_saved += 1
                    logger.info("Saved sample %d (elapsed=%ss)", n_saved, elapsed)

                time.sleep(poll_interval_s)
        except KeyboardInterrupt:
            logger.info("Interrupted by user, finishing up.")
        finally:
            if stop_when_done:
                try:
                    client.stop_measurement()
                except OPSError as e:
                    logger.warning("stop_measurement failed: %s", e)

    if collected_errors:
        _update_errors_row(out_path, "; ".join(dict.fromkeys(collected_errors)))

    return out_path

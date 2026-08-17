"""
Load a .toml "profile" (instrument setup) and push it to the OPS 3330.

A profile describes everything WMODE*/WS* commands can configure: channel
(bin) setup, logging setup, alarm, analog output, user calibration, and
flow calibration. Any section left out of the TOML file is simply skipped
(the instrument keeps whatever is already configured for that section).

See profiles/default_minimal.toml for the standard/factory 16-channel
(0.3 - 10 um) bin table plus a basic logging configuration.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # requires `pip install tomli` on Python < 3.11

from .client import OPSClient

_STATE_MAP = {"off": 0, "0-5v": 1, "4-20ma": 2}


def load_profile(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("rb") as f:
        return tomllib.load(f)


def apply_profile(client: OPSClient, profile: dict[str, Any], commit: bool = True) -> None:
    """
    Push every section present in `profile` to the connected OPS.
    Call with a connected OPSClient. Raises OPSError on any FAIL response.
    """

    if "channels" in profile:
        ch = profile["channels"]
        cut_points = ch["cut_points_um"]
        n = ch.get("number_enabled", len(cut_points) - 1)
        if n != len(cut_points) - 1:
            raise ValueError(
                f"channels.number_enabled ({n}) must equal len(cut_points_um) - 1 "
                f"({len(cut_points) - 1})"
            )
        client.write_channel_setup(cut_points)

    if "logging" in profile:
        lg = profile["logging"]
        client.write_log_setup(
            start_time=lg.get("start_time", "00:00"),
            start_date=lg.get("start_date", "01/01/2026"),
            sample_interval=lg["sample_interval"],
            number_of_samples=lg["number_of_samples"],
            number_of_sets=lg.get("number_of_sets", 1),
            repeat_interval=lg.get("repeat_interval", "0:00:01"),
            use_start_time=lg.get("use_start_time", False),
            use_start_date=lg.get("use_start_date", False),
            logging_enabled=lg.get("logging_enabled", True),
            log_to_single_file=lg.get("log_to_single_file", True),
            survey_mode=lg.get("survey_mode", False),
            keep_pump_running=lg.get("keep_pump_running", True),
        )

    if "alarm" in profile and profile["alarm"].get("enabled", False):
        al = profile["alarm"]
        client.write_alarm_setup(
            visible=al.get("visible", False),
            audible=al.get("audible", False),
            relay=al.get("relay", False),
            measurement_is_dn=(al.get("measurement", "dN").lower() == "dn"),
            threshold=al["threshold"],
        )

    if "analog_output" in profile:
        ao = profile["analog_output"]
        state = ao.get("state", "off")
        state_val = _STATE_MAP.get(str(state).lower(), 0)
        client.write_analog_setup(
            state=state_val,
            measurement_is_dn=(ao.get("measurement", "dN").lower() == "dn"),
            minimum=ao.get("minimum", 0.0),
            maximum=ao.get("maximum", 10000.0),
        )

    if "user_cal" in profile:
        uc = profile["user_cal"]
        client.write_user_cal(
            enabled=uc.get("enabled", False),
            dead_time_correction=uc.get("dead_time_correction", False),
            density=uc.get("density", 1.0),
            refractive_index_real=uc.get("refractive_index_real", 1.5),
            refractive_index_imag=uc.get("refractive_index_imag", 0.0),
            shape_correction_factor=uc.get("shape_correction_factor", 0.0),
        )

    if "flow_cal" in profile:
        fc = profile["flow_cal"]
        client.write_flow_cal(
            user_flow_cal=fc.get("user_flow_cal", 1.0),
            external_flow_control=fc.get("external_flow_control", False),
        )

    if commit:
        # Required: writes only take effect on the instrument after MUPDATE.
        client.commit()

    proto = profile.get("protocol", {})
    if proto.get("save_as_protocol") and proto.get("name"):
        client.save_current_as_protocol(proto["name"])

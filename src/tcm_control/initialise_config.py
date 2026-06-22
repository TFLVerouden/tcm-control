from __future__ import annotations
"""Load and validate experiment input configuration from TOML."""

import re
from pathlib import Path
from typing import Any

from tcm_utils.file_dialogs import ask_open_file

import tomllib


VALID_EXPERIMENT_MODES = {"droplet", "film", "piv"}
PUMP_REQUIRED_MODES = {"droplet", "piv"}


# -----------------------------------------------------------------------------
# Generic value helpers
# -----------------------------------------------------------------------------


def _nested_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely read nested dictionary values with a default fallback."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _normalize_optional_string(value: Any) -> str | None:
    """Convert blank strings to None; otherwise return stripped text."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_optional_path_string(value: Any) -> str | None:
    """Normalize optional path-like strings to use forward slashes."""
    text = _normalize_optional_string(value)
    if text is None:
        return None
    return text.replace("\\", "/")


def _sanitize_windows_path_separators_in_toml(raw_text: str) -> str:
    """Normalize Windows backslashes for selected TOML path keys.

    This targets only basic string assignments for:
    - series_directory
    - append_file_path

    It converts backslashes to forward slashes so TOML parsing remains robust
    when users provide Windows-style paths.
    """

    pattern = re.compile(
        r'(^\s*(series_directory|append_file_path)\s*=\s*")([^"\n]*)(")',
        flags=re.MULTILINE,
    )

    def _replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        path_value = match.group(3)
        suffix = match.group(4)
        return f"{prefix}{path_value.replace('\\', '/')}" + suffix

    return pattern.sub(_replace, raw_text)


def _optional_float(value: Any) -> float | None:
    """Parse optional numeric values as float, allowing empty values."""
    if value is None:
        return None
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _optional_int(value: Any) -> int | None:
    """Parse optional numeric values as integer, allowing empty values."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("Boolean value is not valid for integer field.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    return int(float(text))


def _required_non_negative_int(value: Any, *, default: int = 0) -> int:
    """Parse an integer value that must be zero or positive."""
    parsed = _optional_int(value)
    if parsed is None:
        parsed = default
    if parsed < 0:
        raise ValueError("Expected a non-negative integer value.")
    return parsed


def load_experiment_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load the experiment TOML and return normalized runtime dictionaries.

    If no path is provided, a file picker is shown so users can choose a config.
    """
    if config_path is None:
        default_dir = Path(__file__).resolve().parent / "config"
        selected = ask_open_file(
            key="tcm_experiment_config",
            title="Select experiment config TOML",
            filetypes=(("TOML files", "*.toml"), ("All files", "*.*")),
            default_dir=default_dir,
            start=default_dir,
        )
        if selected is None:
            raise SystemExit("No config TOML selected.")
        config_file = Path(selected)
    else:
        config_file = Path(config_path)

    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    raw_text = config_file.read_text(encoding="utf-8")
    try:
        raw = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError:
        sanitized_text = _sanitize_windows_path_separators_in_toml(raw_text)
        if sanitized_text == raw_text:
            raise
        raw = tomllib.loads(sanitized_text)

    # ------------------------------------------------------------------
    # Experiment-level settings
    # ------------------------------------------------------------------
    experiment_name_raw = _nested_get(raw, "experiment", "name")
    experiment_mode = _nested_get(raw, "experiment", "mode")
    series_directory_raw = _nested_get(raw, "experiment", "series_directory")

    if experiment_name_raw is None:
        raise ValueError(
            "Config [experiment].name must be a string (can be empty to prompt)."
        )
    experiment_name = _normalize_optional_string(experiment_name_raw)
    if experiment_name_raw is not None and not isinstance(experiment_name_raw, str):
        raise ValueError(
            "Config [experiment].name must be a string (can be empty to prompt)."
        )

    if not isinstance(experiment_mode, str) or experiment_mode not in VALID_EXPERIMENT_MODES:
        raise ValueError(
            "Config [experiment].mode must be one of: "
            + ", ".join(sorted(VALID_EXPERIMENT_MODES))
        )

    series_directory = _normalize_optional_path_string(series_directory_raw)
    save_data = True
    if series_directory is not None and series_directory.strip().lower() == "none":
        series_directory = None
        save_data = False

    # ------------------------------------------------------------------
    # Cough run controls
    # ------------------------------------------------------------------
    cough_inputs = {
        "debug_mode": bool(
            _nested_get(raw, "inputs", "cough", "debug_mode", default=False)
        ),
        "nr_runs": int(_nested_get(raw, "inputs", "cough", "nr_runs", default=1)),
        "multi_run_interval_s": float(
            _nested_get(raw, "inputs", "cough",
                        "multi_run_interval_s", default=0.0)
        ),
        "confirm_before_starting_next_run": bool(
            _nested_get(
                raw,
                "inputs",
                "cough",
                "confirm_before_starting_next_run",
                default=True,
            )
        ),
        "record_droplet_size": bool(
            _nested_get(raw, "inputs", "cough",
                        "record_droplet_size", default=False)
        ),
    }
    if cough_inputs["nr_runs"] < 1:
        cough_inputs["nr_runs"] = 1

    # SprayTec is intentionally disabled in PIV mode.
    if experiment_mode == "piv":
        cough_inputs["record_droplet_size"] = False

    # ------------------------------------------------------------------
    # Cough machine inputs
    # ------------------------------------------------------------------
    cough_machine_inputs = {
        "flow_curve_csv_path": _normalize_optional_string(
            _nested_get(
                raw,
                "devices",
                "cough_machine",
                "inputs",
                "flow_curve_csv_path",
            )
        ),
        "wait_before_run_ms": float(
            _nested_get(
                raw,
                "devices",
                "cough_machine",
                "inputs",
                "wait_before_run_ms",
                default=0.0,
            )
        ),
        "tank": {
            "pressure_bar": float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "pressure_bar",
                    default=0.0,
                )
            ),
            "settling_time_s": float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "settling_time_s",
                    default=60.0,
                )
            ),
            "avg_window_s": float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "avg_window_s",
                    default=5.0,
                )
            ),
            "tolerance_bar": float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "tolerance_bar",
                    default=0.05,
                )
            ),
            "poll_interval_s": float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "poll_interval_s",
                    default=0.2,
                )
            ),
            "intermediate_diff_bar": _optional_float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "intermediate_diff_bar",
                )
            ),
            "intermediate_time_s": _optional_float(
                _nested_get(
                    raw,
                    "devices",
                    "cough_machine",
                    "inputs",
                    "tank",
                    "intermediate_time_s",
                )
            ),
        },
    }

    has_intermediate_diff = (
        cough_machine_inputs["tank"]["intermediate_diff_bar"] is not None
    )
    has_intermediate_time = (
        cough_machine_inputs["tank"]["intermediate_time_s"] is not None
    )
    if has_intermediate_diff != has_intermediate_time:
        raise ValueError(
            "Config [devices.cough_machine.inputs.tank] must define both "
            "intermediate_diff_bar and intermediate_time_s together."
        )

    cough_machine_inputs["wait_before_run_us"] = int(
        cough_machine_inputs["wait_before_run_ms"] * 1000
    )

    # ------------------------------------------------------------------
    # Pump inputs (required in droplet/piv mode only)
    # ------------------------------------------------------------------
    pump_required = experiment_mode in PUMP_REQUIRED_MODES
    pump_inputs = {
        "syringe_volume_ml": _optional_float(
            _nested_get(raw, "devices", "pump", "inputs", "syringe_volume_ml")
        ),
        "pump_rate_ml_per_min": _optional_float(
            _nested_get(raw, "devices", "pump",
                        "inputs", "pump_rate_ml_per_min")
        ),
        "nr_droplets_to_skip_before_recording": _required_non_negative_int(
            _nested_get(
                raw,
                "devices",
                "pump",
                "inputs",
                "nr_droplets_to_skip_before_recording",
            )
        ),
        "piv_pump_start_before_run_s": float(
            _nested_get(
                raw,
                "devices",
                "pump",
                "inputs",
                "piv_pump_start_before_run_s",
                default=0.0,
            )
        ),
        "piv_pump_stop_after_run_s": float(
            _nested_get(
                raw,
                "devices",
                "pump",
                "inputs",
                "piv_pump_stop_after_run_s",
                default=0.0,
            )
        ),
        "piv_nebuliser_pressure_bar": float(
            _nested_get(
                raw,
                "devices",
                "pump",
                "inputs",
                "piv_nebuliser_pressure_bar",
                default=0.5,
            )
        ),
    }
    if pump_required and pump_inputs["syringe_volume_ml"] is None:
        raise ValueError(
            "Config [devices.pump.inputs].syringe_volume_ml must be set "
            "for droplet and piv modes."
        )

    if experiment_mode in {"droplet", "piv"}:
        if pump_inputs["pump_rate_ml_per_min"] is None:
            raise ValueError(
                "Config [devices.pump.inputs].pump_rate_ml_per_min "
                "must be set for droplet and piv modes."
            )

    if experiment_mode == "piv":
        if pump_inputs["piv_pump_start_before_run_s"] < 0:
            raise ValueError(
                "Config [devices.pump.inputs].piv_pump_start_before_run_s "
                "must be >= 0."
            )
        if pump_inputs["piv_pump_stop_after_run_s"] < 0:
            raise ValueError(
                "Config [devices.pump.inputs].piv_pump_stop_after_run_s "
                "must be >= 0."
            )
        if pump_inputs["piv_nebuliser_pressure_bar"] <= 0:
            raise ValueError(
                "Config [devices.pump.inputs].piv_nebuliser_pressure_bar "
                "must be > 0."
            )

    if not pump_required:
        pump_inputs = {
            "syringe_volume_ml": None,
            "pump_rate_ml_per_min": None,
            "nr_droplets_to_skip_before_recording": 0,
            "piv_pump_start_before_run_s": 0.0,
            "piv_pump_stop_after_run_s": 0.0,
            "piv_nebuliser_pressure_bar": None,
        }

    # ------------------------------------------------------------------
    # Camera inputs
    # ------------------------------------------------------------------
    camera_exposure_us = int(
        _nested_get(
            raw,
            "devices",
            "camera",
            "inputs",
            "camera_exposure_us",
            default=4000,
        )
    )
    if camera_exposure_us <= 0:
        raise ValueError(
            "Config [devices.camera.inputs].camera_exposure_us must be > 0."
        )
    camera_inputs = {
        "camera_exposure_us": camera_exposure_us,
    }

    record_droplet_size = bool(cough_inputs["record_droplet_size"])

    # ------------------------------------------------------------------
    # Vertical stage inputs
    # ------------------------------------------------------------------
    vertical_stage_inputs = {
        "tolerance_mm": float(
            _nested_get(
                raw,
                "devices",
                "vertical_stage",
                "inputs",
                "tolerance_mm",
                default=0.3,
            )
        ),
        "timeout_s": float(
            _nested_get(
                raw,
                "devices",
                "vertical_stage",
                "inputs",
                "timeout_s",
                default=30.0,
            )
        ),
        "poll_interval_s": float(
            _nested_get(
                raw,
                "devices",
                "vertical_stage",
                "inputs",
                "poll_interval_s",
                default=0.2,
            )
        ),
    }
    if vertical_stage_inputs["tolerance_mm"] < 0:
        raise ValueError(
            "Config [devices.vertical_stage.inputs].tolerance_mm must be >= 0."
        )
    if vertical_stage_inputs["timeout_s"] <= 0:
        raise ValueError(
            "Config [devices.vertical_stage.inputs].timeout_s must be > 0."
        )
    if vertical_stage_inputs["poll_interval_s"] <= 0:
        raise ValueError(
            "Config [devices.vertical_stage.inputs].poll_interval_s must be > 0."
        )

    # ------------------------------------------------------------------
    # SprayTec inputs (validated only when enabled)
    # ------------------------------------------------------------------
    spraytec_inputs = {
        "append_file_path": _normalize_optional_path_string(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "append_file_path")
        ),
        "tcm_trachea_bottom_z_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "tcm_trachea_bottom_z_mm")
        ),
        "tcm_trachea_height_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "tcm_trachea_height_mm")
        ),
        "lift_zero_z_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec", "inputs", "lift_zero_z_mm")
        ),
        "spraytec_to_lift_z_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "spraytec_to_lift_z_mm")
        ),
        "tcm_trachea_exit_to_ref_x_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec", "inputs",
                        "tcm_trachea_exit_to_ref_x_mm")
        ),
        "tcm_trachea_exit_to_ref_y_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec", "inputs",
                        "tcm_trachea_exit_to_ref_y_mm")
        ),
        "spraytec_to_ref_x_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "spraytec_to_ref_x_mm")
        ),
        "spraytec_to_ref_y_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "spraytec_to_ref_y_mm")
        ),
        "stage_pos_x_zero_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "stage_pos_x_zero_mm")
        ),
        "stage_pos_y_zero_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "stage_pos_y_zero_mm")
        ),
        "table_height_mm": _optional_float(
            _nested_get(raw, "devices", "spraytec",
                        "inputs", "table_height_mm")
        ),
        "position": {
            "spraytec_target_z_mm": _optional_float(
                _nested_get(
                    raw,
                    "devices",
                    "spraytec",
                    "inputs",
                    "position",
                    "spraytec_target_z_mm",
                    default=_nested_get(
                        raw,
                        "devices",
                        "spraytec",
                        "inputs",
                        "spraytec_target_z_mm",
                    ),
                )
            ),
            "stage_pos_x_mm": _optional_float(
                _nested_get(
                    raw,
                    "devices",
                    "spraytec",
                    "inputs",
                    "position",
                    "stage_pos_x_mm",
                    default=_nested_get(
                        raw,
                        "devices",
                        "spraytec",
                        "inputs",
                        "stage_pos_x_mm",
                    ),
                )
            ),
            "stage_pos_y_mm": _optional_float(
                _nested_get(
                    raw,
                    "devices",
                    "spraytec",
                    "inputs",
                    "position",
                    "stage_pos_y_mm",
                    default=_nested_get(
                        raw,
                        "devices",
                        "spraytec",
                        "inputs",
                        "stage_pos_y_mm",
                    ),
                )
            ),
        },
    }

    if not record_droplet_size:
        spraytec_inputs = {
            "append_file_path": None,
            "tcm_trachea_bottom_z_mm": None,
            "tcm_trachea_height_mm": None,
            "lift_zero_z_mm": None,
            "spraytec_to_lift_z_mm": None,
            "tcm_trachea_exit_to_ref_x_mm": None,
            "tcm_trachea_exit_to_ref_y_mm": None,
            "spraytec_to_ref_x_mm": None,
            "spraytec_to_ref_y_mm": None,
            "stage_pos_x_zero_mm": None,
            "stage_pos_y_zero_mm": None,
            "table_height_mm": None,
            "position": {
                "spraytec_target_z_mm": None,
                "stage_pos_x_mm": None,
                "stage_pos_y_mm": None,
            },
        }
    else:
        required_spraytec_keys = [
            "tcm_trachea_bottom_z_mm",
            "tcm_trachea_height_mm",
            "lift_zero_z_mm",
            "spraytec_to_lift_z_mm",
            "tcm_trachea_exit_to_ref_x_mm",
            "tcm_trachea_exit_to_ref_y_mm",
            "spraytec_to_ref_x_mm",
            "spraytec_to_ref_y_mm",
            "stage_pos_x_zero_mm",
            "stage_pos_y_zero_mm",
            "table_height_mm",
        ]
        missing = [
            key
            for key in required_spraytec_keys
            if spraytec_inputs.get(key) is None
        ]
        if missing:
            missing_str = ", ".join(missing)
            raise ValueError(
                "SprayTec is enabled, but required fields are empty in "
                f"[devices.spraytec.inputs]: {missing_str}"
            )

    return {
        "experiment": {
            "name": experiment_name,
            "mode": experiment_mode,
            "series_directory": Path(series_directory) if series_directory else None,
            "save_data": save_data,
            "config_file_path": config_file,
        },
        "inputs": {
            "cough": cough_inputs,
        },
        "devices": {
            "cough_machine": {
                "inputs": cough_machine_inputs,
            },
            "pump": {
                "required": pump_required,
                "inputs": pump_inputs,
            },
            "camera": {
                "inputs": camera_inputs,
            },
            "vertical_stage": {
                "inputs": vertical_stage_inputs,
            },
            "spraytec": {
                "enabled": record_droplet_size,
                "inputs": spraytec_inputs,
            },
        },
    }

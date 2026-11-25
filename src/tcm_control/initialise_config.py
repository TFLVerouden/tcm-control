"""Experiment configuration, validation, prompting and template generation."""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, field_validator, model_validator

from tcm_utils.file_dialogs import ask_open_file, ensure_directory_path
from tcm_utils.io_utils import prompt_input
from tcm_control.devices.camera import DEFAULT_SCALE_MM_PER_PX, validate_flip, validate_gain, validate_roi
from tcm_control.devices.ops import MAX_RECORDING_S, validate_bin_boundaries
from tcm_control.devices.cough_machine import (
    DEFAULT_CLEAN_CYCLE_COUNT,
    DEFAULT_CLEAN_DRY_DURATION_S,
    DEFAULT_CLEAN_DRY_VALVE_CURRENT_MA,
    DEFAULT_CLEAN_PRESSURE_BAR,
    DEFAULT_CLEAN_VALVE_OPEN_DURATION_S,
    MAX_PRESSURE_BAR,
)


NonNegative = Annotated[float, Field(ge=0)]
Positive = Annotated[float, Field(gt=0)]
Pressure = Annotated[float, Field(ge=0, le=MAX_PRESSURE_BAR)]


def setting(description: str, *, default: Any = None, required_for: str | None = None) -> Any:
    """Define one setting's default, documentation and conditional prompt."""
    return Field(default=default, description=description,
                 json_schema_extra={"required_for": required_for})


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def empty_optional_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        # Empty numeric/choice fields mean missing; empty strings retain their own semantics.
        return {
            key: None if (item == "" and key in cls.model_fields
                          and type(None) in get_args(cls.model_fields[key].annotation)
                          and str not in get_args(cls.model_fields[key].annotation)) else item
            for key, item in value.items()
        }


class Experiment(Settings):
    name: str | None = setting(
        "Experiment name; leave empty to be prompted when saving (optional).")
    mode: Literal["film", "piv", "droplet"] | None = setting(
        "Experiment mode: \"film\", \"piv\" or \"droplet\".", required_for="mode")
    save_data: StrictBool = setting(
        "Save experiment data to disk.", default=True)
    series_directory: str | None = setting(
        "Series directory; leave empty to select one.")

    @field_validator("name", "series_directory")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class Run(Settings):
    debug_mode: StrictBool = setting(
        "Enable cough-machine debug mode.", default=False)
    fan_off_during_experiment: StrictBool = setting(
        "Turn off fan in electronics box during the experiment.", default=True)
    nr_runs: int = setting("Number of coughs in the experiment.", default=1)
    multi_run_interval_s: float = setting(
        "Wait between runs in seconds.", default=0.0)
    confirm_before_starting_next_run: StrictBool = setting(
        "Ask for confirmation before each subsequent run.", default=True)
    flow_curve_csv_path: str | None = setting(
        "Flow-curve path or name; leave empty to select a CSV.")
    wait_before_run_ms: float = setting(
        "Controller pre-trigger wait in milliseconds.", default=0.0)

    @field_validator("nr_runs")
    @classmethod
    def at_least_one_run(cls, value: int) -> int:
        return max(1, value)

    @field_validator("flow_curve_csv_path")
    @classmethod
    def normalize_flow_curve(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class Tank(Settings):
    pressure_bar: Pressure | None = setting(
        "Tank pressure in bar.", required_for="always")
    settling_time_s: float = setting(
        "Pressure settling timeout in seconds.", default=60.0)
    avg_window_s: float = setting(
        "Pressure averaging window in seconds.", default=5.0)
    tolerance_bar: float = setting("Pressure tolerance in bar.", default=0.05)
    poll_interval_s: float = setting(
        "Pressure polling interval in seconds.", default=0.2)
    intermediate_diff_bar: float | None = setting(
        "Intermediate pressure difference in bar; set together with intermediate_time_s.")
    intermediate_time_s: float | None = setting(
        "Intermediate pressure hold time in seconds; set together with intermediate_diff_bar.")

    @model_validator(mode="after")
    def paired_intermediate_settings(self) -> Tank:
        if (self.intermediate_diff_bar is None) != (self.intermediate_time_s is None):
            raise ValueError(
                "intermediate_diff_bar and intermediate_time_s must be set together")
        return self


class Cleaning(Settings):
    clean_pressure_bar: Pressure = setting(
        "Cleaning pressure in bar.", default=DEFAULT_CLEAN_PRESSURE_BAR)
    valve_open_duration_s: Positive = setting(
        "Valve-open duration in seconds.", default=DEFAULT_CLEAN_VALVE_OPEN_DURATION_S)
    cycle_count: Annotated[int, Field(ge=0)] = setting(
        "Number of cleaning cycles before drying.", default=DEFAULT_CLEAN_CYCLE_COUNT)
    dry_pressure_bar: Pressure | None = setting(
        "Drying pressure in bar; omit to use cleaning pressure.")
    dry_duration_s: NonNegative = setting(
        "Drying duration in seconds.", default=DEFAULT_CLEAN_DRY_DURATION_S)
    dry_valve_current_ma: Positive = setting(
        "Drying valve current in mA.", default=DEFAULT_CLEAN_DRY_VALVE_CURRENT_MA)


class Nebuliser(Settings):
    fill_time_s: NonNegative = setting(
        "Nebuliser filling time in seconds.", default=60.0)
    pressure_bar: Positive = setting("Nebuliser pressure in bar.", default=0.1)
    pre_run_start_s: NonNegative = setting(
        "Nebulisation time before the cough in seconds.", default=0.0)
    post_run_finish_s: NonNegative = setting(
        "Nebulisation time after the cough in seconds.", default=0.0)


class RunSettings(Run):
    tank: Tank = Field(default_factory=Tank)
    cleaning: Cleaning = Field(default_factory=Cleaning)


class Droplet(Settings):
    nr_droplets_to_skip_before_recording: Annotated[int, Field(ge=0)] = setting(
        "Droplets to skip before recording in droplet mode.", default=0)


class Syringe(Settings):
    syringe_vendor_code: str | None = setting(
        "Syringe vendor code.", required_for="film")
    syringe_volume_mL: Positive | None = setting(
        "Syringe volume in mL.", required_for="film")
    syringe_diameter_mm: Positive | None = setting(
        "Syringe diameter in mm.", required_for="film")
    syringe_gang: Annotated[int, Field(gt=0)] | None = setting(
        "Number of syringes in the gang.", required_for="film")
    syringe_force_percent: Annotated[float, Field(gt=0, le=100)] | None = setting(
        "Pump force in percent, in multiples of 10.", required_for="film")

    @field_validator("syringe_vendor_code")
    @classmethod
    def nonempty_vendor(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("syringe_force_percent")
    @classmethod
    def force_step(cls, value: float | None) -> float | None:
        if value is not None and value % 10:
            raise ValueError("syringe force must be a multiple of 10")
        return value


def _prompt_syringe_profile(syringe: Syringe, contexts: set[str]) -> None:
    """Fill unspecified film syringe settings from a selectable profile."""
    if "film" not in contexts or all(
            getattr(syringe, name) is not None for name in Syringe.model_fields):
        return

    lookup_path = (
        Path(__file__).resolve().parent
        / "devices" / "lookup_tables" / "syringes.toml"
    )
    profiles = tomllib.loads(
        lookup_path.read_text(encoding="utf-8"))["profiles"]
    profile_items = list(profiles.items())

    print("Syringe settings are incomplete. Select a syringe profile:")
    for index, (name, profile) in enumerate(profile_items, start=1):
        print(
            f"  {index}. {name}: {profile['vendor_code']} "
            f"{profile['volume_ml']:g} mL, {profile['diameter_mm']:g} mm, "
            f"gang {profile['gang']}, force {profile['force_percent']:g}%"
        )
    selection = prompt_input(
        "Profile number (fills only unspecified syringe settings): ",
        value_type="int", min_value=1, max_value=len(profile_items),
    )
    profile = profile_items[selection - 1][1]
    profile_values = {
        name: profile[key]
        for name, key in (
            ("syringe_vendor_code", "vendor_code"),
            ("syringe_volume_mL", "volume_ml"),
            ("syringe_diameter_mm", "diameter_mm"),
            ("syringe_gang", "gang"),
            ("syringe_force_percent", "force_percent"),
        )
        if getattr(syringe, name) is None
    }
    updated = Syringe.model_validate(
        {**syringe.model_dump(), **profile_values})
    for name in Syringe.model_fields:
        setattr(syringe, name, getattr(updated, name))


class Layer(Settings):
    film_settling_time_s: Annotated[int, Field(ge=0)] | None = setting(
        "Film settling time in seconds.", required_for="film")
    infuse_volume_ml: NonNegative | None = setting(
        "Volume infused to make the layer in mL.", required_for="film")
    infuse_rate_ml_min: Positive | None = setting(
        "Layer infusion rate in mL/min.", required_for="film")
    withdraw_volume_ml: NonNegative | None = setting(
        "Volume withdrawn to make the layer in mL.", required_for="film")
    withdraw_rate_ml_min: Positive | None = setting(
        "Layer withdrawal rate in mL/min.", required_for="film")


class CleanTube(Settings):
    volume_ml_layer: NonNegative | None = setting(
        "Initial tube-cleaning infusion volume in mL.", required_for="clean_tube")
    rate_ml_min_layer: Positive | None = setting(
        "Initial tube-cleaning rate in mL/min.", required_for="clean_tube")
    volume_ml_repetition: NonNegative | None = setting(
        "Volume per tube-cleaning repetition in mL.", required_for="clean_repetition")
    rate_ml_min_repetition: Positive | None = setting(
        "Tube-cleaning repetition rate in mL/min.", required_for="clean_repetition")
    repetitions: Annotated[int, Field(ge=0)] = setting(
        "Number of tube-cleaning repetitions.", default=0)


class Film(Settings):
    layer: Layer = Field(default_factory=Layer)
    clean_tube: CleanTube = Field(default_factory=CleanTube)


class PIV(Settings):
    nebuliser: Nebuliser = Field(default_factory=Nebuliser)


class CameraInputs(Settings):
    led_brightness: Positive | None = setting(
        "Cough machine LED lamp brightness (between 0 and 1), default 1.0.", default=1.0)
    camera_exposure_us: Annotated[int, Field(gt=0)] = setting(
        "Camera exposure in microseconds.", default=4000)
    camera_gain_db: float | None = setting(
        "Camera gain in dB; default is 0.0.", default=0.0)
    roi: tuple[int, int, int, int] = setting(
        "ROI [y_start, y_end, x_start, x_end]; end 0 means full extent.", default=(0, 0, 0, 0))
    flip: Literal["vertical", "horizontal", "both"] | None = setting(
        "Camera flip; empty disables it.", default="vertical")
    scale_mm_per_px: Positive | None = setting(
        "Camera calibration in mm per pixel.", default=DEFAULT_SCALE_MM_PER_PX, required_for="film")
    live_preview: StrictBool = setting(
        "Show the live film preview.", default=True)

    @field_validator("roi", mode="before")
    @classmethod
    def check_roi(cls, value: object) -> tuple[int, int, int, int]:
        return validate_roi(value)

    @field_validator("flip", mode="before")
    @classmethod
    def check_flip(cls, value: object) -> str | None:
        return validate_flip(None if value == "" else value)

    @field_validator("camera_gain_db", mode="before")
    @classmethod
    def check_gain(cls, value: object) -> float | None:
        return validate_gain(value)


class SprayTecPosition(Settings):
    spraytec_target_z_mm: float | None = setting(
        "Target SprayTec height in mm; leave empty to prompt.")
    stage_pos_x_mm: float | None = setting(
        "Stage x ruler reading in mm; leave empty to prompt.")
    stage_pos_y_mm: float | None = setting(
        "Stage y ruler reading in mm; leave empty to prompt.")


class SprayTecGeometry(Settings):
    tcm_trachea_bottom_z_mm: float | None = setting(
        "Trachea bottom height in mm.", required_for="spraytec")
    tcm_trachea_height_mm: float | None = setting(
        "Trachea height in mm.", required_for="spraytec")
    lift_zero_z_mm: float | None = setting(
        "Lift zero height in mm.", required_for="spraytec")
    spraytec_to_lift_z_mm: float | None = setting(
        "SprayTec-to-lift vertical offset in mm.", required_for="spraytec")
    tcm_trachea_exit_to_ref_x_mm: float | None = setting(
        "Trachea-exit x offset from reference in mm.", required_for="spraytec")
    tcm_trachea_exit_to_ref_y_mm: float | None = setting(
        "Trachea-exit y offset from reference in mm.", required_for="spraytec")
    spraytec_to_ref_x_mm: float | None = setting(
        "SprayTec x offset from reference in mm.", required_for="spraytec")
    spraytec_to_ref_y_mm: float | None = setting(
        "SprayTec y offset from reference in mm.", required_for="spraytec")
    stage_pos_x_zero_mm: float | None = setting(
        "Stage x zero ruler reading in mm.", required_for="spraytec")
    stage_pos_y_zero_mm: float | None = setting(
        "Stage y zero ruler reading in mm.", required_for="spraytec")
    table_height_mm: float | None = setting(
        "Table height in mm.", required_for="spraytec")
    position: SprayTecPosition = Field(default_factory=SprayTecPosition)


class SprayTec(Settings):
    enabled: StrictBool = setting(
        "Enable SprayTec recording in film mode.", default=False)
    append_file_path: str | None = setting(
        "SprayTec append file; leave empty to select it.")

    @field_validator("append_file_path")
    @classmethod
    def normalize_append_path(cls, value: str | None) -> str | None:
        return value.strip().replace("\\", "/") or None if value is not None else None


class OPSGeometry(Settings):
    position: str = setting(
        "OPS position description; leave empty to prompt.", default="")

    @field_validator("position")
    @classmethod
    def normalize_position(cls, value: str) -> str:
        return value.strip()


class OPS(Settings):
    enabled: StrictBool = setting(
        "Enable OPS recording in film mode.", default=False)
    pre_run_s: NonNegative | None = setting(
        "OPS recording time before the cough in seconds.", required_for="ops")
    post_run_s: NonNegative | None = setting(
        "OPS recording time after the cough in seconds.", required_for="ops")
    alarm_threshold: Annotated[float, Field(ge=0, le=10000)] | None = setting(
        "OPS concentration alarm threshold in particles/cm3.", required_for="ops")
    bin_boundaries_um: list[float] | None = setting(
        "17 OPS bin boundaries in micrometres, from 0.3 to 10.", required_for="ops")

    @field_validator("bin_boundaries_um", mode="before")
    @classmethod
    def check_boundaries(cls, value: object) -> list[float] | None:
        return None if value is None else validate_bin_boundaries(value)

    @model_validator(mode="after")
    def check_duration(self) -> OPS:
        if (self.pre_run_s is not None and self.post_run_s is not None
                and self.pre_run_s + self.post_run_s >= MAX_RECORDING_S):
            raise ValueError(
                "OPS pre- and post-run durations must total less than the recording limit")
        return self


class Devices(Settings):
    syringe_pump: Syringe = Field(default_factory=Syringe)
    camera: CameraInputs = Field(default_factory=CameraInputs)
    spraytec: SprayTec = Field(default_factory=SprayTec)
    ops: OPS = Field(default_factory=OPS)


class Geometry(Settings):
    spraytec: SprayTecGeometry = Field(default_factory=SprayTecGeometry)
    ops: OPSGeometry = Field(default_factory=OPSGeometry)


class ExperimentConfig(Settings):
    experiment: Experiment = Field(default_factory=Experiment)
    run: RunSettings = Field(default_factory=RunSettings)
    film: Film = Field(default_factory=Film,
                       description="Settings used in film mode.")
    piv: PIV = Field(default_factory=PIV,
                     description="Settings used in PIV mode.")
    droplet: Droplet = Field(default_factory=Droplet,
                             description="Settings used in droplet mode.")
    devices: Devices = Field(default_factory=Devices,
                             description="Device configuration.")
    geometry: Geometry = Field(
        default_factory=Geometry, description="Measurement geometry and positions.")


def _prompt_required(model: Settings, contexts: set[str], prefix: str = "") -> None:
    """Resolve missing fields applicable to the current experiment or action."""
    for name, field in type(model).model_fields.items():
        value = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, Settings):
            _prompt_required(value, contexts, path)
            continue
        required_for = (field.json_schema_extra or {}).get("required_for")
        if value is not None or required_for not in contexts:
            continue
        while True:
            description = (field.description or "").strip().removesuffix(".")
            if description:
                description = description[0].lower() + description[1:]
            text = prompt_input(
                f'Specify {description} ("config.{path}"): ',
                value_type="string")
            candidate: Any = text
            if name == "bin_boundaries_um":
                candidate = [item.strip()
                             for item in text.strip("[]").split(",")]
            try:
                updated = type(model).model_validate(
                    {**model.model_dump(), name: candidate})
            except ValidationError as exc:
                print(f"Invalid value for {path}: {exc}")
                continue
            setattr(model, name, getattr(updated, name))
            break


def resolve_tube_cleaning(inputs: dict[str, Any]) -> dict[str, Any]:
    """Prompt for tube-cleaning values only when the operator selects cleaning."""
    cleaning = CleanTube.model_validate(inputs)
    contexts = {"clean_tube"}
    if cleaning.repetitions:
        contexts.add("clean_repetition")
    _prompt_required(cleaning, contexts, "film.clean_tube")
    return cleaning.model_dump()


def _read_toml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        # Preserve support for Windows paths entered without escaped backslashes.
        sanitized = re.sub(
            r'(^\s*(?:series_directory|append_file_path)\s*=\s*")([^"\n]*)(")',
            lambda match: match.group(
                1) + match.group(2).replace("\\", "/") + match.group(3),
            text, flags=re.MULTILINE,
        )
        if sanitized == text:
            raise
        return tomllib.loads(sanitized)


def load_experiment_config(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load TOML, resolve applicable required settings, and return runtime values."""
    if config_path is None:
        default_dir = Path(__file__).resolve().parent / "config"
        config_path = ask_open_file(
            key="tcm_experiment_config", title="Select experiment config TOML",
            filetypes=(("TOML files", "*.toml"), ("All files", "*.*")),
            default_dir=default_dir, start=default_dir,
        )
        if config_path is None:
            raise SystemExit("No config TOML selected.")
    config_file = Path(config_path)
    raw = _read_toml(config_file)

    # Disabled devices do not require or validate their device-specific inputs.
    experiment = Experiment.model_validate(raw.get("experiment", {}))
    _prompt_required(experiment, {"mode"}, "experiment")
    raw["experiment"] = experiment.model_dump()
    devices = raw.get("devices", {})
    if not isinstance(devices, dict):
        raise ValueError("Config [devices] must be a table.")
    mode = experiment.mode
    if mode == "piv":
        devices.pop("syringe_pump", None)
        raw.pop("film", None)
    geometry = raw.get("geometry", {})
    if not isinstance(geometry, dict):
        raise ValueError("Config [geometry] must be a table.")
    for name in ("ops", "spraytec"):
        device = devices.get(name, {})
        if isinstance(device, dict) and "enabled" in device and not isinstance(device["enabled"], bool):
            raise ValueError(
                f"Config [devices.{name}].enabled must be a boolean.")
        if isinstance(device, dict) and (mode == "piv" or device.get("enabled", False) is False):
            devices[name] = {"enabled": False}
            geometry.pop(name, None)
            if mode == "piv":
                devices[name]["enabled"] = False

    config = ExperimentConfig.model_validate(raw)
    if config.experiment.mode == "piv":
        config.devices.ops.enabled = False
        config.devices.spraytec.enabled = False
    contexts = {"always"}
    if config.experiment.mode == "film":
        contexts.add("film")
        if config.devices.ops.enabled:
            contexts.add("ops")
        if config.devices.spraytec.enabled:
            contexts.add("spraytec")
    _prompt_syringe_profile(config.devices.syringe_pump, contexts)
    _prompt_required(config, contexts)

    if config.experiment.save_data:
        selected = ensure_directory_path(
            config.experiment.series_directory, key="tcm_series_directory",
            title="Select series directory",
            start=Path(__file__).resolve().parent,
        )
        if selected is None:
            raise SystemExit("No series directory selected.")
        config.experiment.series_directory = str(selected)
    else:
        config.experiment.series_directory = None

    result = config.model_dump()
    result["experiment"]["config_file_path"] = config_file
    result["run"]["wait_before_run_us"] = int(
        config.run.wait_before_run_ms * 1000)
    return result


def render_config_template(*, include_comments: bool = True) -> str:
    """Generate a TOML template from the field definitions."""
    lines: list[str] = []

    def render(model: type[Settings], section: str, description: str | None = None) -> None:
        fields = model.model_fields
        leaves = [(name, field) for name, field in fields.items()
                  if not isinstance(field.annotation, type) or not issubclass(field.annotation, Settings)]
        indent = "    " * section.count(".")
        lines.append(f"{indent}[{section}]")
        if description and include_comments:
            lines.append(f"{indent}# {description}")
        if leaves:
            for name, field in leaves:
                if include_comments:
                    lines.append(f"{indent}# {field.description}")
                value = field.get_default(call_default_factory=True)
                if value is None:
                    if include_comments:
                        extra = field.json_schema_extra
                        required_for = extra.get("required_for") if isinstance(
                            extra, dict) else None
                        note = "prompted when required" if required_for else "optional; see description"
                        lines.append(f"{indent}# {name} =  # {note}")
                    else:
                        lines.append(f'{indent}{name} = ""')
                else:
                    default = json.dumps(value)
                    line = f"{indent}{name} = {default}"
                    if include_comments:
                        line += f"  # optional; default: {default}"
                    lines.append(line)
        lines.append("")
        for name, field in fields.items():
            if isinstance(field.annotation, type) and issubclass(field.annotation, Settings):
                render(
                    field.annotation, f"{section}.{name}" if section else name, field.description)

    for name, field in ExperimentConfig.model_fields.items():
        render(field.annotation, name, field.description)
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate a documented experiment config template.")
    parser.add_argument(
        "output", type=Path, help="New TOML file to create (existing files are not overwritten).")
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as file:
        file.write(render_config_template())

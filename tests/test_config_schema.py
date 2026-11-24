"""Configuration-only checks; no device connections are made."""

import inspect
import json
import runpy
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from tcm_control.initialise_config import (
    ExperimentConfig,
    load_experiment_config,
    render_config_template,
    resolve_tube_cleaning,
)
from tcm_control.devices.camera import DEFAULT_SCALE_MM_PER_PX
from tcm_control.devices.spraytec import SprayTec
from tcm_control.devices.vertical_stage import (
    DEFAULT_POLL_INTERVAL_S, DEFAULT_TIMEOUT_S, DEFAULT_TOLERANCE_MM, VerticalStage,
)
from tcm_control.logger import build_run_metadata, write_run_metadata
from tcm_control.user_input import set_spraytec_pos


class ConfigSchemaTests(unittest.TestCase):
    def load(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(text, encoding="utf-8")
            return load_experiment_config(path)

    def test_piv_defaults_and_unsupported_devices(self):
        config = self.load("""
[experiment]
mode = "piv"
series_directory = "None"
[run.tank]
pressure_bar = 2.5
[devices.spraytec]
enabled = true
[devices.ops]
enabled = true
pre_run_s = "unused"
""")
        self.assertFalse(config["experiment"]["save_data"])
        self.assertFalse(config["run"]["debug_mode"])
        self.assertFalse(config["devices"]["ops"]["enabled"])
        self.assertFalse(config["devices"]["spraytec"]["enabled"])
        camera = config["devices"]["camera"]
        self.assertEqual(camera["flip"], "vertical")
        self.assertTrue(camera["live_preview"])
        self.assertEqual(camera["scale_mm_per_px"], DEFAULT_SCALE_MM_PER_PX)
        tank = config["run"]["tank"]
        self.assertEqual((tank["pressure_bar"], tank["settling_time_s"]), (2.5, 60.0))

    def test_missing_pressure_is_prompted_and_validated(self):
        text = '[experiment]\nmode = "piv"\nseries_directory = "None"\n'
        with patch("tcm_control.initialise_config.prompt_input", side_effect=["8", "2.5"]) as prompt:
            config = self.load(text)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(config["run"]["tank"]["pressure_bar"], 2.5)

    def test_camera_scale_in_saved_metadata_uses_default_or_override(self):
        class MetadataSource:
            def metadata(self):
                return {}

        base = '[experiment]\nmode = "piv"\nseries_directory = "None"\n[run.tank]\npressure_bar = 2\n'
        for camera_section, expected in (("", DEFAULT_SCALE_MM_PER_PX),
                                         ("\n[devices.camera]\nscale_mm_per_px = 0.02\n", 0.02)):
            config = self.load(base + camera_section)
            with tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                metadata = build_run_metadata(config, time_start="start", output_dir=directory,
                                              tcm=MetadataSource())
                write_run_metadata(directory, metadata)
                saved = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
                self.assertEqual(saved["configuration"]["devices"]["camera"]["scale_mm_per_px"], expected)

    def test_missing_series_directory_is_selected(self):
        text = '[experiment]\nmode = "piv"\n[run.tank]\npressure_bar = 2\n'
        with patch("tcm_control.initialise_config.ensure_directory_path", return_value=Path("/selected")) as picker:
            config = self.load(text)
        picker.assert_called_once()
        self.assertEqual(config["experiment"]["series_directory"], "/selected")
        self.assertTrue(config["experiment"]["save_data"])

    def test_film_only_prompts_for_applicable_missing_settings(self):
        text = """
[experiment]
mode = "film"
series_directory = "None"
[run.tank]
pressure_bar = 2.5
[devices.syringe_pump]
syringe_vendor_code = "hm2"
syringe_volume_mL = 100
syringe_diameter_mm = 32
syringe_gang = 1
syringe_force_percent = 100
[film.layer]
film_settling_time_s = 30
infuse_volume_ml = 3.5
infuse_rate_ml_min = 15
withdraw_volume_ml = 2.5
withdraw_rate_ml_min = 5
"""
        with patch("tcm_control.initialise_config.prompt_input") as prompt:
            config = self.load(text)
        prompt.assert_not_called()
        self.assertFalse(config["devices"]["ops"]["enabled"])
        self.assertFalse(config["devices"]["spraytec"]["enabled"])

    def test_cleaning_fields_are_prompted_only_when_used(self):
        with patch("tcm_control.initialise_config.prompt_input", side_effect=["3", "15"]) as prompt:
            result = resolve_tube_cleaning({"repetitions": 0})
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual((result["volume_ml_layer"], result["rate_ml_min_layer"]), (3, 15))
        self.assertIsNone(result["volume_ml_repetition"])

    def test_cleaning_repetitions_prompt_for_their_own_settings(self):
        with patch("tcm_control.initialise_config.prompt_input", side_effect=["3", "15", "0.5", "5"]):
            result = resolve_tube_cleaning({"repetitions": 2})
        self.assertEqual((result["volume_ml_repetition"], result["rate_ml_min_repetition"]), (0.5, 5))

    def test_invalid_ops_fields_and_unknown_settings_are_rejected(self):
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"pre_run_s": 50, "post_run_s": 10}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"alarm_threshold": 10001}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"bin_boundaries_um": [0.3] * 17}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"geometry": {"ops": {"position": 123}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"run": {"unknown": 1}})

    def test_device_flags_are_independent(self):
        for ops in (False, True):
            for spraytec in (False, True):
                config = ExperimentConfig.model_validate({
                    "devices": {"ops": {"enabled": ops}, "spraytec": {"enabled": spraytec}},
                })
                self.assertEqual(config.devices.ops.enabled, ops)
                self.assertEqual(config.devices.spraytec.enabled, spraytec)

    def test_enabled_ops_prompts_and_retries_invalid_duration(self):
        source = Path("src/tcm_control/config/config_spraytec.toml").read_text(encoding="utf-8")
        source = source.replace("pre_run_s = 10.0\n", "").replace("post_run_s = 10.0\n", "")
        with patch("tcm_control.initialise_config.ensure_directory_path", return_value=Path("/selected")):
            with patch("tcm_control.initialise_config.prompt_input", side_effect=["50", "10", "9"]) as prompt:
                config = self.load(source)
        self.assertEqual(prompt.call_count, 3)
        ops = config["devices"]["ops"]
        self.assertEqual((ops["pre_run_s"], ops["post_run_s"]), (50, 9))

    def test_generated_template_is_current_and_valid_toml(self):
        generated = render_config_template()
        template = Path("src/tcm_control/config/config_template.toml")
        self.assertEqual(template.read_text(encoding="utf-8"), generated)
        parsed = tomllib.loads(generated)
        self.assertFalse(parsed["devices"]["ops"]["enabled"])
        self.assertFalse(parsed["devices"]["spraytec"]["enabled"])
        self.assertNotIn("pressure_bar", parsed["run"]["tank"])
        self.assertNotIn("drying", parsed["run"])
        self.assertNotIn("vertical_stage", parsed["devices"])
        self.assertLess(generated.index("cycle_count ="), generated.index("# dry_pressure_bar"))

    def test_template_indentation_matches_section_depth(self):
        generated = render_config_template()
        depth = 0
        for line in generated.splitlines():
            if not line.strip():
                continue
            text = line.lstrip()
            if text.startswith("["):
                depth = text[1:text.index("]")].count(".")
            self.assertEqual(len(line) - len(text), depth * 4, line)
        unindented = "\n".join(line.lstrip() for line in generated.splitlines())
        self.assertEqual(tomllib.loads(generated), tomllib.loads(unindented))

    def test_template_includes_parent_sections_with_descriptions(self):
        generated = render_config_template()
        for section, description in (
            ("film", "Settings used in film mode."),
            ("piv", "Settings used in PIV mode."),
            ("devices", "Device configuration."),
            ("geometry", "Measurement geometry and positions."),
        ):
            self.assertIn(f"[{section}]\n# {description}", generated)
        self.assertIn("[film.layer]", generated)
        self.assertIn("[piv.nebuliser]", generated)

    def test_vertical_stage_defaults_are_shared_by_call_chain(self):
        expected = {"tolerance_mm": DEFAULT_TOLERANCE_MM, "timeout_s": DEFAULT_TIMEOUT_S,
                    "poll_interval_s": DEFAULT_POLL_INTERVAL_S}
        for function in (set_spraytec_pos, VerticalStage.set_spraytec_height, VerticalStage.set_lift_height):
            parameters = inspect.signature(function).parameters
            self.assertEqual({name: parameters[name].default for name in expected}, expected)

    def test_template_documents_all_defaults(self):
        generated = render_config_template()
        assignments = [line.strip() for line in generated.splitlines()
                       if line.strip() and not line.lstrip().startswith(("#", "["))]
        self.assertTrue(assignments)
        for line in assignments:
            assignment, note = line.split("  # ", 1)
            default = assignment.split(" = ", 1)[1]
            self.assertEqual(note, f"optional; default: {default}")
        self.assertIn("debug_mode = false  # optional; default: false", generated)

    def test_active_config_is_valid_toml_and_uses_camera_default(self):
        path = Path("src/tcm_control/config/config_spraytec.toml")
        parsed = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertNotIn("scale_mm_per_px", parsed["devices"]["camera"])
        config = ExperimentConfig.model_validate(parsed)
        self.assertEqual(config.devices.camera.scale_mm_per_px, DEFAULT_SCALE_MM_PER_PX)

    def test_active_film_config_retains_device_and_geometry_settings(self):
        source = Path("src/tcm_control/config/config_spraytec.toml").read_text(encoding="utf-8")
        raw = tomllib.loads(source)
        with patch("tcm_control.initialise_config.ensure_directory_path", return_value=Path("/selected")):
            with patch("tcm_control.initialise_config.prompt_input") as prompt:
                config = self.load(source)
        prompt.assert_not_called()
        self.assertTrue(config["devices"]["ops"]["enabled"])
        self.assertTrue(config["devices"]["spraytec"]["enabled"])
        self.assertEqual(config["geometry"], raw["geometry"])
        self.assertEqual(config["film"]["layer"], raw["film"]["layer"])
        self.assertEqual(config["devices"]["syringe_pump"], raw["devices"]["syringe_pump"])
        self.assertEqual(config["run"]["cleaning"], raw["run"]["cleaning"])

    def test_regeneration_script_replaces_only_its_template(self):
        source = Path("src/tcm_control/config/regenerate_template.py").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            script = directory / "regenerate_template.py"
            template = directory / "config_template.toml"
            other_config = directory / "config_spraytec.toml"
            script.write_text(source, encoding="utf-8")
            template.write_text("outdated", encoding="utf-8")
            other_config.write_text("keep", encoding="utf-8")
            runpy.run_path(str(script), run_name="__main__")
            self.assertEqual(template.read_text(encoding="utf-8"), render_config_template())
            self.assertEqual(other_config.read_text(encoding="utf-8"), "keep")

    def test_metadata_snapshot_replaces_previous_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_run_metadata(directory, {"status": "in_progress"})
            write_run_metadata(directory, {"status": "completed", "path": directory})
            saved = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(saved, {"status": "completed", "path": str(directory)})
            self.assertFalse((directory / ".metadata.json.tmp").exists())

    def test_device_metadata_is_included_in_snapshots(self):
        class MetadataSource:
            def __init__(self, value):
                self.value = value

            def metadata(self):
                return {"settings": {"value": self.value}}

        tcm = MetadataSource("tcm")
        stage = MetadataSource("stage")
        camera = MetadataSource("camera")
        pump = MetadataSource("pump")
        spraytec = SprayTec(max_append_file_size_bytes=123, offer_archive_if_large=False)
        metadata = build_run_metadata(
            {}, time_start="start", output_dir=Path("."), tcm=tcm,
            pump=pump, camera=camera, vertical_stage=stage, spraytec=spraytec,
            spraytec_x_mm=5,
        )
        devices = metadata["runtime"]["devices"]
        self.assertEqual(devices["cough_machine"]["settings"]["value"], "tcm")
        self.assertEqual(devices["vertical_stage"]["settings"]["value"], "stage")
        self.assertEqual(devices["camera"]["settings"]["value"], "camera")
        self.assertEqual(devices["pump"]["settings"]["value"], "pump")
        self.assertEqual(devices["spraytec"]["settings"], {
            "max_append_file_size_bytes": 123, "offer_archive_if_large": False,
        })
        self.assertEqual(devices["spraytec"]["measurement_position_mm"]["x"], 5)
        self.assertIsNone(devices["ops"])


if __name__ == "__main__":
    unittest.main()

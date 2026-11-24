"""Configuration-only checks; no device connections are made."""

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
from tcm_control.logger import write_run_metadata


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
[devices.cough_machine.inputs.tank]
pressure_bar = 2.5
[devices.spraytec]
enabled = true
[devices.ops]
enabled = true
[devices.ops.inputs]
pre_run_s = "unused"
""")
        self.assertFalse(config["experiment"]["save_data"])
        self.assertFalse(config["inputs"]["cough"]["debug_mode"])
        self.assertFalse(config["devices"]["ops"]["enabled"])
        self.assertFalse(config["devices"]["spraytec"]["enabled"])
        camera = config["devices"]["camera"]["inputs"]
        self.assertEqual(camera["flip"], "vertical")
        self.assertTrue(camera["live_preview"])
        self.assertEqual(camera["scale_mm_per_px"], DEFAULT_SCALE_MM_PER_PX)
        tank = config["devices"]["cough_machine"]["inputs"]["tank"]
        self.assertEqual((tank["pressure_bar"], tank["settling_time_s"]), (2.5, 60.0))

    def test_missing_pressure_is_prompted_and_validated(self):
        text = '[experiment]\nmode = "piv"\nseries_directory = "None"\n'
        with patch("tcm_control.initialise_config.prompt_input", side_effect=["8", "2.5"]) as prompt:
            config = self.load(text)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(config["devices"]["cough_machine"]["inputs"]["tank"]["pressure_bar"], 2.5)

    def test_missing_series_directory_is_selected(self):
        text = '[experiment]\nmode = "piv"\n[devices.cough_machine.inputs.tank]\npressure_bar = 2\n'
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
[devices.cough_machine.inputs.tank]
pressure_bar = 2.5
[devices.pump.syringe]
syringe_vendor_code = "hm2"
syringe_volume_mL = 100
syringe_diameter_mm = 32
syringe_gang = 1
syringe_force_percent = 100
[devices.pump.layer]
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
            ExperimentConfig.model_validate({"devices": {"ops": {"inputs": {"pre_run_s": 50, "post_run_s": 10}}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"inputs": {"alarm_threshold": 10001}}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"inputs": {"bin_boundaries_um": [0.3] * 17}}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"devices": {"ops": {"inputs": {"position": 123}}}})
        with self.assertRaises(ValidationError):
            ExperimentConfig.model_validate({"inputs": {"cough": {"unknown": 1}}})

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
        ops = config["devices"]["ops"]["inputs"]
        self.assertEqual((ops["pre_run_s"], ops["post_run_s"]), (50, 9))

    def test_generated_template_is_current_and_valid_toml(self):
        generated = render_config_template()
        template = Path("src/tcm_control/config/config_template.toml")
        self.assertEqual(template.read_text(encoding="utf-8"), generated)
        parsed = tomllib.loads(generated)
        self.assertFalse(parsed["devices"]["ops"]["enabled"])
        self.assertFalse(parsed["devices"]["spraytec"]["enabled"])
        self.assertNotIn("pressure_bar", parsed["devices"]["cough_machine"]["inputs"]["tank"])

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
        self.assertNotIn("scale_mm_per_px", parsed["devices"]["camera"]["inputs"])
        config = ExperimentConfig.model_validate(parsed)
        self.assertEqual(config.devices.camera.inputs.scale_mm_per_px, DEFAULT_SCALE_MM_PER_PX)

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


if __name__ == "__main__":
    unittest.main()

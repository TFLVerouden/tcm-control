import csv
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def progress(**_kwargs):
    yield types.SimpleNamespace(update=lambda _n: None)


def fake_module(**values):
    return types.SimpleNamespace(**values)


class RunOutputTests(unittest.TestCase):
    def test_temperature_humidity_csv_and_failures(self):
        modules = {
            "tcm_utils.file_dialogs": fake_module(ask_open_file=None, find_repo_root=None),
            "tcm_utils.io_utils": fake_module(countdown_beep=None, make_minimal_progress_bar=None, beep=None),
            "tcm_control.devices.base": fake_module(PoFSerialDevice=object),
            "tcm_control.logger": fake_module(copy_flow_curve=None, create_labeled_csv_filename=None),
        }
        with patch.dict(sys.modules, modules), tempfile.TemporaryDirectory() as tmp:
            machine_module = load_module(
                "tcm_control.devices.cough_machine", "src/tcm_control/devices/cough_machine.py")
            machine = machine_module.CoughMachine.__new__(machine_module.CoughMachine)
            machine.name = "fake"
            machine._query_and_drain = MagicMock(return_value=("T21.5 H45.2", []))
            csv_path = Path(tmp) / "reading.csv"
            self.assertEqual(machine.read_temperature_humidity(save_csv=csv_path), (21.5, 45.2))
            with csv_path.open() as file:
                self.assertEqual(list(csv.reader(file)),
                                 [["temperature_degC", "relative_humidity_percent"], ["21.5", "45.2"]])
            machine._query_and_drain.return_value = ("Tbad H45", [])
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(machine.read_temperature_humidity(show_reading=True, save_csv=csv_path),
                                 (None, None))
            self.assertIn("WARNING: Temperature or humidity", out.getvalue())
            with csv_path.open() as file:
                self.assertEqual(list(csv.reader(file))[1], ["", ""])
            with self.assertRaises(FileNotFoundError):
                machine.read_temperature_humidity(save_csv=Path(tmp) / "missing" / "reading.csv")

    def test_film_and_piv_outputs(self):
        for mode, count, save, fail_fan in (("film", 1, True, False), ("film", 2, True, False),
                ("piv", 1, True, False), ("piv", 2, True, False), ("piv", 2, False, False),
                ("piv", 1, True, True)):
            with self.subTest(mode=mode, count=count, save=save, fail_fan=fail_fan), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                events = []
                readings = iter([(18, 30)] + [(None, 40 + n) for n in range(count)] + [(19, 50)])

                class Machine:
                    FAN_SPEED_OFF = 0
                    FAN_SPEED_MAX = 1
                    FAN_SPEED_DEFAULT = 2
                    name = "fake"
                    serial_settings = {}

                    def __init__(self, **_kwargs):
                        pass

                    def __getattr__(self, name):
                        return lambda *args, **kwargs: None

                    def get_flowcurve_csv_path(self):
                        return Path("curve.csv")

                    def set_fan_speed(self, speed):
                        if fail_fan and speed == self.FAN_SPEED_DEFAULT:
                            raise RuntimeError("fan reset failed")

                    def _query_and_drain(self, *_args, **_kwargs):
                        events.append("reading")
                        temperature, humidity = next(readings)
                        reply = None if temperature is None else f"T{temperature} H{humidity}"
                        return reply, []

                    def read_temperature_humidity(self, **kwargs):
                        return machine_module.CoughMachine.read_temperature_humidity(self, **kwargs)

                    def start_run(self):
                        events.append("start")

                    def run(self, **kwargs):
                        events.append("start")
                        return self.receive_run_log(**kwargs)

                    def receive_run_log(self, output_dir, run_nr_start, save_logs):
                        if not save_logs:
                            return None
                        path = output_dir / "run_logs" / f"log{run_nr_start}.csv"
                        path.parent.mkdir()
                        path.write_text("log")
                        return path

                class Camera:
                    def __init__(self, output_dir, **_kwargs):
                        self.output_dir = output_dir

                class OPSClient:
                    def __init__(self, **_kwargs):
                        pass

                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        pass

                    def read_model_number(self):
                        return "fake"

                class OPS:
                    def __init__(self, _client):
                        pass

                    def read_status(self):
                        return "ready"

                    def start_standard_recording(self, out_csv_path, **_kwargs):
                        self.path = out_csv_path
                        self.path.write_text("OPS")

                    def collect_recording(self):
                        return self.path

                def snapshot(camera, _machine, filename):
                    path = camera.output_dir / f"{filename}.tif"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("image")
                    return path

                def plot(run_log_path, experiment_dir, **_kwargs):
                    target = experiment_dir / "processed"
                    target.mkdir()
                    (target / "plot.pdf").write_text(str(run_log_path))

                cleaning = dict.fromkeys(("clean_pressure_bar", "valve_open_duration_s",
                                          "dry_pressure_bar", "dry_duration_s",
                                          "dry_valve_current_ma", "cycle_count"), 0)
                config = {
                    "experiment": {"mode": mode, "save_data": save, "series_directory": str(root),
                                   "name": "test", "config_file_path": root / "config.toml"},
                    "inputs": {"cough": {"debug_mode": False, "nr_runs": count,
                                          "record_droplet_size": False, "multi_run_interval_s": 0,
                                          "confirm_before_starting_next_run": False}},
                    "devices": {
                        "cough_machine": {"inputs": {"tank": dict.fromkeys(
                            ("pressure_bar", "settling_time_s", "avg_window_s", "tolerance_bar",
                             "poll_interval_s", "intermediate_diff_bar", "intermediate_time_s"), 0),
                            "cleaning": cleaning, "drying": cleaning, "wait_before_run_us": 0,
                            "flow_curve_csv_path": "curve.csv",
                            "nebuliser": {"pressure_bar": 0, "fill_time_s": 0,
                                          "pre_run_start_s": 0, "post_run_finish_s": 0}}},
                        "pump": {"syringe": dict.fromkeys(("syringe_vendor_code", "syringe_volume_mL",
                            "syringe_diameter_mm", "syringe_gang", "syringe_force_percent"), 0),
                            "layer": dict.fromkeys(("infuse_volume_ml", "infuse_rate_ml_min",
                                "withdraw_volume_ml", "withdraw_rate_ml_min", "film_settling_time_s"), 0),
                            "clean_tube": {}},
                        "camera": {"inputs": {"camera_exposure_us": 1, "roi": [], "flip": None,
                                               "camera_gain_db": 0, "scale_mm_per_px": 1}},
                        "vertical_stage": {"inputs": {}}, "spraytec": {"inputs": {}},
                    },
                }
                (root / "config.toml").write_text("")
                output = root / "experiment"
                logger = fake_module(
                    ConsoleLogCapture=MagicMock(), create_pending_console_log_path=lambda: root / "pending",
                    latest_experiment_display_name=lambda _p: None,
                    create_experiment_dir=lambda *_a, **_kw: (output.mkdir() or output),
                    copy_experiment_config=lambda **_kw: None, create_console_log_path=lambda _p: root / "log",
                    build_run_metadata=lambda _c, **kw: kw,
                    write_run_metadata=lambda **_kw: None,
                )
                noop = lambda *args, **kwargs: None
                modules = {
                    "tcm_control": fake_module(logger=logger),
                    "tcm_control.devices": fake_module(CoughMachine=Machine, Camera=Camera,
                        SyringePump=MagicMock(), VerticalStage=MagicMock(), SprayTec=MagicMock()),
                    "tcm_control.devices.spraytec": fake_module(warn_if_experiment_dir_name_too_long=noop),
                    "tcm_control.initialise_config": fake_module(load_experiment_config=lambda _p: config),
                    "tcm_control.interrupt_handling": fake_module(**dict.fromkeys(
                        ("reset_interrupt_cleanup_state", "set_active_output_dir", "set_active_pump", "set_active_tcm"), noop)),
                    "tcm_control.processing.run_log_processing": fake_module(plot_run_log=plot),
                    "tcm_control.imaging": fake_module(take_snapshot=snapshot),
                    "tcm_control.processing.determine_film_height": fake_module(
                        measure_plate_height=lambda _p: (10, 1, None, None, None),
                        measure_film_properties=lambda *_a: (2, 0.1, 45, 12)),
                    "tcm_control.user_input": fake_module(**dict.fromkeys(
                        ("ask_start_confirmation", "ask_user_for_comments", "set_spraytec_pos", "wait_or_confirm_next_run"), noop)),
                    "tcm_utils.file_dialogs": fake_module(ensure_directory_path=lambda *_a, **_kw: root,
                        ask_open_file=noop, find_repo_root=lambda: root),
                    "tcm_utils.io_utils": fake_module(ensure_non_empty_text=lambda text, **_kw: text,
                        prompt_input=noop, prompt_yes_no=lambda *_a, **_kw: False
                        if _a and _a[0].startswith("Do you want") else True,
                        wait_with_progress=noop, beep=noop, countdown_beep=noop,
                        make_minimal_progress_bar=progress, create_timestamped_filename=noop,
                        save_metadata_json=noop),
                    "tcm_utils.time_utils": fake_module(timestamp_str=lambda: "261124_083347",
                                                       timestamp_from_file=noop),
                    "tcm_control.devices.base": fake_module(PoFSerialDevice=object),
                    "tcm_control.logger": logger,
                    "tcm_control.devices.ops3330.ops3330": fake_module(OPSClient=OPSClient, OPS=OPS),
                    "tcm_control.devices.ops3330.ops3330.VisualiseData": fake_module(OPS_visualize_data=noop),
                }
                with patch.dict(sys.modules, modules), redirect_stdout(io.StringIO()) as out:
                    actual_logger = load_module("_test_logger", "src/tcm_control/logger.py")
                    logger.create_run_dir = actual_logger.create_run_dir
                    logger.write_film_measurement = actual_logger.write_film_measurement
                    logger.copy_flow_curve = actual_logger.copy_flow_curve
                    logger.create_labeled_csv_filename = actual_logger.create_labeled_csv_filename
                    machine_module = load_module(
                        "tcm_control.devices.cough_machine", "src/tcm_control/devices/cough_machine.py")
                    runner = load_module("_test_cough", "src/tcm_control/cough.py")
                    setattr(runner, "time", fake_module(sleep=noop))
                    if fail_fan:
                        with self.assertRaisesRegex(RuntimeError, "fan reset failed"):
                            runner.cough()
                        logger.ConsoleLogCapture.return_value.close.assert_called_once()
                    else:
                        self.assertEqual(runner.cough(), output if save else None)
                self.assertIn("WARNING: Temperature or humidity", out.getvalue())
                self.assertEqual(events, ["reading"] + ["reading", "start"] * count
                                 + (["reading"] if save else []))
                if not save:
                    self.assertFalse(output.exists())
                    continue
                for n in range(1, count + 1):
                    run = output / ("run" if count == 1 else f"run{n}")
                    with (run / "temperature_humidity.csv").open() as file:
                        self.assertEqual(list(csv.reader(file))[1], ["", ""])
                    self.assertTrue((run / "run_logs" / f"log{n}.csv").exists())
                    self.assertTrue((run / "processed" / "plot.pdf").exists())
                    if mode == "film":
                        self.assertEqual(len(list((run / "camera").glob("*.tif"))), 3)
                        self.assertEqual(len(list((run / "OPS_data").glob("*_OPS.csv"))), 1)
                        with (run / "film_measurement.csv").open() as file:
                            row = next(csv.DictReader(file))
                        self.assertEqual((row["run_nr"], row["film_height_mm"]), (str(n), "2"))

    def test_spraytec_matching_and_unmatched(self):
        modules = {
            "tcm_utils.io_utils": fake_module(ask_open_file=None, make_minimal_progress_bar=progress,
                                               prompt_yes_no=lambda *_a, **_kw: False),
            "tcm_utils.time_utils": fake_module(timestamp_str=lambda dt=None, include_us=False:
                dt.strftime("%y%m%d_%H%M%S_%f") if dt else "261124_083347"),
            "tcm_control.logger": fake_module(create_labeled_csv_filename=lambda prefix, label, timestamp:
                                               f"{prefix}{label or ''}_{timestamp}.csv"),
        }
        for times, expected in (([2, 1], "matched"), ([1], "unmatched"),
                                ([1, 2, 3], "unmatched"), ([1, 1], "unmatched")):
            with self.subTest(times=times), tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules, modules):
                spraytec = load_module("_test_spraytec", "src/tcm_control/devices/spraytec.py")
                root = Path(tmp).resolve()
                experiment = root / "experiment"
                experiment.mkdir()
                runs = [experiment / "run1", experiment / "run2"]
                for run in runs:
                    run.mkdir()
                source = root / "append.csv"
                source.write_text("".join(
                    f"Date-Time,Material,Lot Value\n24 Nov 2026 08:00:0{n},water,1\n"
                    for n in times
                ))
                with redirect_stdout(io.StringIO()) as out:
                    device = spraytec.SprayTec(source, experiment, offer_archive_if_large=False)
                    audit = device.save_data(start_time="261124_075959", run_dirs=runs)
                with audit.open() as file:
                    rows = list(csv.DictReader(file))
                self.assertTrue(all(Path(row["experiment_csv"]).exists() for row in rows))
                if expected == "matched":
                    self.assertEqual(Path(rows[0]["experiment_dir"]), runs[1] / "spraytec")
                    self.assertEqual(Path(rows[1]["experiment_dir"]), runs[0] / "spraytec")
                else:
                    self.assertIn("WARNING: Cannot match", out.getvalue())
                    self.assertTrue(all(Path(row["experiment_dir"]) == experiment / "spraytec_unmatched"
                                        for row in rows))
                with redirect_stdout(io.StringIO()):
                    device.save_data(start_time="261124_075959", run_dirs=runs)
                self.assertEqual(len(list(experiment.rglob("spraytec*.csv"))), len(times))

    def test_experiment_metadata_keeps_ambient_but_not_film_measurements(self):
        modules = {
            "tcm_utils.io_utils": fake_module(create_timestamped_filename=None, save_metadata_json=None),
            "tcm_utils.time_utils": fake_module(timestamp_str=None, timestamp_from_file=None),
        }
        with patch.dict(sys.modules, modules):
            logger = load_module("_test_logger", "src/tcm_control/logger.py")
            config = {"inputs": {"cough": {"debug_mode": False, "nr_runs": 1,
                      "multi_run_interval_s": 0, "confirm_before_starting_next_run": False,
                      "record_droplet_size": False}}, "experiment": {"config_file_path": "test.toml"}}
            values: dict[str, Any] = dict.fromkeys(("experiment_name", "time_start", "time_finish", "output_dir",
                "wait_before_run_us", "comments", "cough_machine_inputs", "pump", "syringe_inputs",
                "layer_inputs", "camera_inputs", "spraytec_inputs", "spraytec_x_mm", "spraytec_y_mm",
                "spraytec_z_mm", "stage_pos_x_mm", "stage_pos_y_mm", "stage_pos_z_mm",
                "spraytec_audit_path", "spraytec_laser_intensity", "vertical_stage"))
            values.update(experiment_mode="film", tcm=fake_module(name="fake", serial_settings={}),
                          temperature_start=18, temperature_finish=19, humidity_start=30, humidity_finish=50)
            measurements = logger.build_run_metadata(config, **values)["experiment"]["measurements"]
            self.assertEqual(measurements, {"temperature": {"start": 18, "finish": 19},
                                            "humidity": {"start": 30, "finish": 50}})


if __name__ == "__main__":
    unittest.main()

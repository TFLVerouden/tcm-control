import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Importing liquid_film first avoids the existing devices/logger import cycle.
import tcm_control.liquid_film  # noqa: F401
from tcm_control.devices.cough_machine import CoughMachine


class RunLogSavingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.output_dir = Path(self.temp_dir.name)
        self.machine = CoughMachine.__new__(CoughMachine)

    def test_single_run_saves_directly_in_run_folder(self):
        run_dir = self.output_dir / "run1"
        run_dir.mkdir()
        with patch.object(self.machine, "_receive_run_log", return_value=["run_nr,99\n", "data\n"]):
            path = self.machine.receive_run_log(output_dir=run_dir, run_nr_start=1)

        assert path is not None
        self.assertEqual(path.parent, run_dir)
        self.assertEqual(path.read_text(), "run_nr,1\ndata\n")
        self.assertFalse((run_dir / "run_logs").exists())

    def test_droplet_batch_saves_each_run_in_its_own_folder(self):
        existing_run = self.output_dir / "run5"
        existing_run.mkdir()
        (existing_run / "measurement.txt").write_text("keep")

        def detect(*, nr_droplets, on_detected):
            for number in range(1, nr_droplets + 1):
                on_detected(number)
            return nr_droplets

        with (
            patch.object(self.machine, "_query_and_drain", return_value=("DROPLET_ARMED", [])),
            patch.object(self.machine, "_await_droplet_events", side_effect=detect),
            patch.object(
                self.machine, "_receive_run_log",
                side_effect=[["run_nr,99\n", "first\n"], ["run_nr,99\n", "second\n"]],
            ),
        ):
            paths = self.machine.detect_droplets_and_run(
                nr_runs=2, run_nr_start=5, output_dir=self.output_dir
            )

        self.assertEqual([path.parent.name for path in paths], ["run5", "run6"])
        self.assertEqual(paths[0].read_text(), "run_nr,5\nfirst\n")
        self.assertEqual(paths[1].read_text(), "run_nr,6\nsecond\n")
        self.assertEqual((existing_run / "measurement.txt").read_text(), "keep")
        self.assertFalse((self.output_dir / "run_logs").exists())

    def test_default_destination_and_unlabeled_droplet_batch(self):
        with patch("tcm_control.devices.cough_machine.find_repo_root", return_value=self.output_dir):
            single = self.machine._save_run_logs(["run_nr,9\n"])
            batch = self.machine._save_run_logs(
                [["run_nr,11\n"], ["run_nr,12\n"]], separate_run_dirs=True
            )

        self.assertEqual(single[0].parent, self.output_dir / ".logs")
        self.assertEqual(
            [path.parent.name for path in batch], ["run1", "run2"]
        )
        self.assertEqual(batch[0].read_text(), "run_nr,11\n")
        self.assertEqual(batch[1].read_text(), "run_nr,12\n")

    def test_single_droplet_and_saving_disabled(self):
        def detect(*, nr_droplets, on_detected):
            on_detected(1)
            return 1

        with (
            patch.object(self.machine, "_query_and_drain", return_value=("DROPLET_ARMED", [])),
            patch.object(self.machine, "_await_droplet_events", side_effect=detect),
            patch.object(self.machine, "_receive_run_log", return_value=["run_nr,1\n"]),
        ):
            paths = self.machine.detect_droplets_and_run(
                nr_runs=1, output_dir=self.output_dir
            )
            unsaved_dir = self.output_dir / "unsaved"
            unsaved = self.machine.detect_droplets_and_run(
                nr_runs=1, output_dir=unsaved_dir, save_logs=False
            )

        self.assertEqual(paths[0].parent, self.output_dir / "run")
        self.assertEqual(unsaved, [])
        self.assertFalse(unsaved_dir.exists())


if __name__ == "__main__":
    unittest.main()

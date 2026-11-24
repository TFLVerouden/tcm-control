import contextlib
import io
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class RunEntryTests(unittest.TestCase):
    def run_entry(self, arguments):
        cough = Mock()
        modules = {
            "tcm_control.cough": types.SimpleNamespace(cough=cough),
            "tcm_control.interrupt_handling": types.SimpleNamespace(
                cleanup_on_interrupt=Mock(), handle_sigint=Mock()
            ),
        }
        with patch.dict(sys.modules, modules), patch.object(sys, "argv", ["run.py", *arguments]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit:
                runpy.run_path(str(ROOT / "run.py"), run_name="__main__")
        return exit.exception.code, cough

    def test_selected_config_is_passed_to_cough(self):
        config = Path("some directory") / "experiment.toml"
        code, cough = self.run_entry([str(config)])
        self.assertEqual(code, 0)
        cough.assert_called_once_with(config)

    def test_no_argument_requests_config_selection(self):
        code, cough = self.run_entry([])
        self.assertEqual(code, 0)
        cough.assert_called_once_with(None)

    def test_extra_arguments_do_not_start_experiment(self):
        code, cough = self.run_entry(["first.toml", "second.toml"])
        self.assertEqual(code, 2)
        cough.assert_not_called()


if __name__ == "__main__":
    unittest.main()

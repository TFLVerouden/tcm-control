import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import tifffile

from tcm_control.devices.camera import Camera
from tcm_control.devices.syringe_pump import SyringePump
from tcm_control.imaging import LayerPreview, layer_preview
from tcm_control.processing.determine_film_height import (
    measure_film_frame,
    measure_film_properties,
)


class LayerPreviewTests(unittest.TestCase):
    def test_frame_and_snapshot_share_flip_and_crop(self):
        source = np.arange(30, dtype=np.uint8).reshape(5, 6)
        camera = Camera.__new__(Camera)
        camera._cam = MagicMock()
        camera._img = MagicMock()
        camera._img.get_image_data_numpy.return_value = source
        camera.start = MagicMock()
        camera.flip = "vertical"
        camera.roi = (1, -1, 2, 0)
        with tempfile.TemporaryDirectory() as tmp:
            camera.output_dir = Path(tmp)
            frame = camera.capture_frame()
            path = camera.snapshot(filename="test")
            np.testing.assert_array_equal(frame, source[::-1][1:-1, 2:])
            np.testing.assert_array_equal(tifffile.imread(path), frame)
            source[:] = 0
            self.assertTrue(np.any(frame))

    def test_preview_measurement_matches_saved_image(self):
        frame = np.zeros((100, 400), dtype=np.uint8)
        cv2.line(frame, (0, 65), (120, 65), 255, 2)
        cv2.line(frame, (120, 65), (160, 50), 255, 2)
        cv2.line(frame, (160, 50), (399, 50), 255, 2)
        plate = (35.0, 0.0, np.arange(400), np.full(400, 35), frame.shape)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "film.tif"
            tifffile.imwrite(path, frame)
            measurement, image = measure_film_frame(frame, plate, 0.01)
            self.assertEqual(measurement, measure_film_properties(path, plate, 0.01, Path(tmp)))
            self.assertEqual(image.shape, (100, 400, 3))
            self.assertTrue((Path(tmp) / "film_processed.png").exists())

    def test_close_continues_and_unavailable_measurements_are_shown(self):
        camera = MagicMock()
        camera.capture_frame.return_value = np.zeros((100, 400), dtype=np.uint8)
        machine = MagicMock()
        plate = (35.0, 0.0, np.arange(400), np.full(400, 35), (100, 400))
        with patch("tcm_control.imaging.cv2.namedWindow"), \
             patch("tcm_control.imaging.cv2.destroyWindow") as destroy, \
             patch("tcm_control.imaging.cv2.getWindowProperty", return_value=1), \
             patch("tcm_control.imaging.cv2.imshow") as show, \
             patch("tcm_control.imaging.cv2.waitKey", return_value=ord("q")):
            with layer_preview(camera, machine, plate, 0.01) as preview:
                preview.update()
                preview.update()
            self.assertEqual(camera.capture_frame.call_count, 1)
            show.assert_called_once()
            destroy.assert_called_once()
            self.assertEqual(machine.set_light.call_args_list, [unittest.mock.call(1.0), unittest.mock.call(0)])

    def test_pump_polling_refreshes_preview(self):
        pump = SyringePump.__new__(SyringePump)
        pump._send = MagicMock(side_effect=["running", "t*"])
        pump._decode_response = MagicMock(return_value=("", False))
        pump.cmd_status = "status"
        pump.status_poll_s = 0.02
        pump.phase_timeout_s = 1
        update = MagicMock()
        self.assertTrue(pump._wait_until_phase_complete("infusion", update))
        update.assert_called()

    def test_closed_window_stops_preview_without_capturing(self):
        camera = MagicMock()
        machine = MagicMock()
        preview = LayerPreview(camera, machine, (0, 0, np.array([]), np.array([]), (1, 1)), 1)
        with patch("tcm_control.imaging.cv2.namedWindow"), \
             patch("tcm_control.imaging.cv2.destroyWindow"), \
             patch("tcm_control.imaging.cv2.getWindowProperty", return_value=0):
            preview.open()
            preview.update()
            preview.update()
        camera.capture_frame.assert_not_called()
        machine.set_light.assert_called_with(0)
        self.assertFalse(preview.active)

    def test_preview_open_failure_turns_light_off(self):
        machine = MagicMock()
        machine.set_light.side_effect = [RuntimeError("light failure"), None]
        with patch("tcm_control.imaging.cv2.namedWindow"), \
             patch("tcm_control.imaging.cv2.destroyWindow"):
            with self.assertRaisesRegex(RuntimeError, "light failure"):
                with layer_preview(MagicMock(), machine, (0, 0, np.array([]), np.array([]), (1, 1)), 1):
                    pass
        self.assertEqual(machine.set_light.call_args_list, [unittest.mock.call(1.0), unittest.mock.call(0)])


if __name__ == "__main__":
    unittest.main()

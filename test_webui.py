import tempfile
import unittest
import sys
import json
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

import main
import webui
import vector_compat


class WebUiTests(unittest.TestCase):
    def test_mode_isolates_dd_and_power_scales_steps(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "app_dir", return_value=Path(tmp)):
            app = webui.App(main)
            with patch.object(main.ctypes, "WinDLL", side_effect=AssertionError("DD loaded in hardware mode"), create=True):
                app.action("/api/mode", {"mode": "hardware"})
                self.assertEqual(app.state()["settings"]["device"], "KMBOXNET")
                self.assertIsInstance(main.make_mouse(app.settings), main.KmboxNetMouse)
            app.action("/api/mode", {"mode": "driver"})
            self.assertEqual(app.state()["settings"]["device"], "DD")
            self.assertIsInstance(main.make_mouse(app.settings), main.DdMouse)
        self.assertEqual(main.build_steps({"path": [{"dx": 4, "dy": 8}], "power": 50, "y_power": 50}, {"sensitivity": 1}), [(2, 2, 0.01)])

    def test_vector_image_and_trajectory_semantics(self):
        class FixedRandom:
            def gauss(self, mean, sigma):
                return mean

            def random(self):
                return 0.5

        weapon = {"level": 6, "frequency": 100, "decline": 10, "initial_drop": 20,
                  "adjustments": [{"start_time": 0, "duration": 1, "direction": "down_left", "intensity": 4}]}
        self.assertEqual(vector_compat.legacy_step(weapon, .1, .1, 0, True, 1, FixedRandom()), (2.8, 6.2))
        self.assertEqual(vector_compat.legacy_step(weapon, .2, .1, 1, False, 1, FixedRandom()), (-.2, 1.2))
        image = main.np.arange(100 * 64, dtype=main.np.uint8).reshape(64, 100)
        self.assertAlmostEqual(vector_compat.score(image, image), .84)

    def test_dd_is_initialized_once_per_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            dll_file = Path(tmp) / "dd63330.dll"
            dll_file.write_bytes(b"test")
            fake = Mock()
            fake.DD_btn.return_value = 1
            with patch.object(main.ctypes, "WinDLL", return_value=fake, create=True) as load:
                a = main.DdMouse(str(dll_file))
                b = main.DdMouse(str(dll_file))
                a.connect()
                a.close()
                b.connect()
                b.move_relative(3, 4)
                load.assert_called_once()
                fake.DD_btn.assert_called_once_with(0)
                fake.DD_movR.assert_called_once_with(3, 4)
            main._DD_DLL = None
            main._DD_INITIALIZED = False

    def test_ui_opens_native_window_and_stops_server_on_close(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "app_dir", return_value=Path(tmp)):
            app = webui.App(main)
            native = Mock()

            def check_window(**kwargs):
                self.assertEqual(kwargs["gui"], "edgechromium")
                url = native.create_window.call_args.args[1]
                with urllib.request.urlopen(url + "api/state") as response:
                    self.assertIsNone(json.load(response)["mode"])

            native.start.side_effect = check_window
            with patch.dict(sys.modules, {"webview": native}):
                app.run()
            native.create_window.assert_called_once()
            native.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()

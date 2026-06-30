import unittest
from types import ModuleType, SimpleNamespace


try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    flask_stub = ModuleType("flask")

    class DummyFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}
            self.secret_key = None

        def __setattr__(self, name, value):
            object.__setattr__(self, name, value)

        def __getattr__(self, name):
            if name == "config":
                object.__setattr__(self, name, {})
                return self.config
            raise AttributeError(name)

        def update(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return lambda fn: fn

        def run(self, *args, **kwargs):
            pass

    flask_stub.Flask = DummyFlask
    flask_stub.Response = object
    flask_stub.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    flask_stub.redirect = lambda *args, **kwargs: None
    flask_stub.render_template = lambda *args, **kwargs: ""
    flask_stub.request = SimpleNamespace(args={}, json=None, form={}, method="GET")
    flask_stub.send_file = lambda *args, **kwargs: None
    flask_stub.session = {}
    flask_stub.url_for = lambda endpoint, **kwargs: endpoint

    import sys

    sys.modules["flask"] = flask_stub

import app as app_module
from app import KioskManager, parse_xrandr_monitors


XRANDR_SAMPLE = """
Screen 0: minimum 16 x 16, current 3840 x 1080, maximum 32767 x 32767
lease-HDMI-A-2 disconnected (normal left inverted right x axis y axis)
   1920x1080     60.00 +  59.94    50.00
HDMI-A-2 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
   1920x1080     59.96*+
lease-HDMI-A-1 disconnected (normal left inverted right x axis y axis)
   1920x1080     60.00 +  59.94    50.00
HDMI-A-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 600mm x 340mm
   1920x1080     59.96*+
"""


class MonitorParsingTests(unittest.TestCase):
    def test_parse_xrandr_monitors_ignores_lease_outputs(self):
        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)

        self.assertEqual([m["name"] for m in monitors], ["HDMI-A-2", "HDMI-A-1"])
        self.assertNotIn("lease-HDMI-A-1", [m["name"] for m in monitors])
        self.assertNotIn("lease-HDMI-A-2", [m["name"] for m in monitors])

    def test_parse_xrandr_monitors_reads_geometry(self):
        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)

        self.assertEqual(monitors[0]["geometry"], "1920x1080+0+0")
        self.assertEqual(monitors[0]["width"], 1920)
        self.assertEqual(monitors[0]["height"], 1080)
        self.assertEqual(monitors[0]["x"], 0)
        self.assertEqual(monitors[0]["y"], 0)
        self.assertTrue(monitors[0]["active"])
        self.assertEqual(monitors[1]["geometry"], "1920x1080+1920+0")
        self.assertEqual(monitors[1]["x"], 1920)


class OutputAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.manager = KioskManager()
        self.monitors = parse_xrandr_monitors(XRANDR_SAMPLE)

    def test_explicit_output_matches_only_active_physical_output(self):
        screen = {"output": "HDMI-A-1"}

        monitor = self.manager._pick_output(screen, self.monitors, 0)

        self.assertIsNotNone(monitor)
        self.assertEqual(monitor["name"], "HDMI-A-1")

    def test_missing_explicit_output_is_unassigned(self):
        screen = {"output": "lease-HDMI-A-1"}

        monitor = self.manager._pick_output(screen, self.monitors, 0)

        self.assertIsNone(monitor)

    def test_automatic_assignment_uses_filtered_active_outputs(self):
        first = self.manager._pick_output({"output": ""}, self.monitors, 0)
        second = self.manager._pick_output({"output": ""}, self.monitors, 1)
        third = self.manager._pick_output({"output": ""}, self.monitors, 2)

        self.assertEqual(first["name"], "HDMI-A-2")
        self.assertEqual(second["name"], "HDMI-A-1")
        self.assertIsNone(third)

    def test_automatic_assignment_stays_bound_when_one_monitor_is_removed(self):
        first = self.manager._pick_output({"output": ""}, self.monitors, 0)
        second = self.manager._pick_output({"output": ""}, self.monitors, 1)
        remaining_right_monitor = [self.monitors[1]]

        moved_first = self.manager._pick_output({"output": ""}, remaining_right_monitor, 0)
        still_second = self.manager._pick_output({"output": ""}, remaining_right_monitor, 1)

        self.assertEqual(first["name"], "HDMI-A-2")
        self.assertEqual(second["name"], "HDMI-A-1")
        self.assertIsNone(moved_first)
        self.assertEqual(still_second["name"], "HDMI-A-1")

    def test_automatic_assignment_does_not_guess_when_monitors_are_missing(self):
        remaining_right_monitor = [self.monitors[1]]

        first = self.manager._pick_output(
            {"output": ""}, remaining_right_monitor, 0, allow_new_auto=False)
        second = self.manager._pick_output(
            {"output": ""}, remaining_right_monitor, 1, allow_new_auto=False)

        self.assertIsNone(first)
        self.assertIsNone(second)

    def test_start_all_persists_complete_automatic_assignment(self):
        saved_configs = []
        original_detect_monitors = app_module.detect_monitors
        original_save_config = app_module.save_config

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, dict(screen), monitor))

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

            def _ensure_watcher(self):
                pass

        cfg = {
            "screens": [
                {"name": "Links", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://left"},
                {"name": "Rechts", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://right"},
            ],
            "chromium_flags": [],
        }

        try:
            app_module.detect_monitors = lambda: self.monitors
            app_module.save_config = lambda value: saved_configs.append(value)
            manager = RecordingManager()

            manager.start_all(cfg)
        finally:
            app_module.detect_monitors = original_detect_monitors
            app_module.save_config = original_save_config

        self.assertEqual(cfg["screens"][0]["output"], "HDMI-A-2")
        self.assertEqual(cfg["screens"][1]["output"], "HDMI-A-1")
        self.assertEqual(len(saved_configs), 1)
        self.assertEqual([item[2]["name"] for item in manager.started],
                         ["HDMI-A-2", "HDMI-A-1"])

    def test_start_all_does_not_bind_disabled_automatic_screens(self):
        saved_configs = []
        original_detect_monitors = app_module.detect_monitors
        original_save_config = app_module.save_config

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []
                self.stopped = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, dict(screen), monitor))

            def stop_screen(self, idx):
                self.stopped.append(idx)

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

            def _ensure_watcher(self):
                pass

        cfg = {
            "screens": [
                {"name": "Disabled", "enabled": False, "output": "",
                 "hide_cursor": False, "url": "http://disabled"},
                {"name": "Rechts", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://right"},
            ],
            "chromium_flags": [],
        }

        try:
            app_module.detect_monitors = lambda: self.monitors
            app_module.save_config = lambda value: saved_configs.append(value)
            manager = RecordingManager()

            manager.start_all(cfg)
        finally:
            app_module.detect_monitors = original_detect_monitors
            app_module.save_config = original_save_config

        self.assertEqual(cfg["screens"][0]["output"], "")
        self.assertEqual(cfg["screens"][1]["output"], "HDMI-A-1")
        self.assertEqual(manager.stopped, [0])
        self.assertEqual([item[0] for item in manager.started], [1])
        self.assertEqual([item[2]["name"] for item in manager.started],
                         ["HDMI-A-1"])
        self.assertEqual(len(saved_configs), 1)

    def test_start_all_recomputes_automatic_after_config_clears_output(self):
        saved_configs = []
        original_detect_monitors = app_module.detect_monitors
        original_save_config = app_module.save_config

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, dict(screen), monitor))

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

            def _ensure_watcher(self):
                pass

        cfg = {
            "screens": [
                {"name": "Links", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://left"},
                {"name": "Rechts", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://right"},
            ],
            "chromium_flags": [],
        }

        try:
            app_module.detect_monitors = lambda: self.monitors
            app_module.save_config = lambda value: saved_configs.append(value)
            manager = RecordingManager()
            manager.output_bindings[0] = "HDMI-A-1"

            manager.start_all(cfg)
        finally:
            app_module.detect_monitors = original_detect_monitors
            app_module.save_config = original_save_config

        self.assertEqual(cfg["screens"][0]["output"], "HDMI-A-2")
        self.assertEqual(cfg["screens"][1]["output"], "HDMI-A-1")
        self.assertEqual([item[2]["name"] for item in manager.started],
                         ["HDMI-A-2", "HDMI-A-1"])
        self.assertEqual(len(saved_configs), 1)

    def test_start_all_automatic_avoids_already_reserved_output(self):
        saved_configs = []
        original_detect_monitors = app_module.detect_monitors
        original_save_config = app_module.save_config

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, dict(screen), monitor))

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

            def _ensure_watcher(self):
                pass

        cfg = {
            "screens": [
                {"name": "First", "enabled": True, "output": "HDMI-A-1",
                 "hide_cursor": False, "url": "http://first"},
                {"name": "Second", "enabled": True, "output": "",
                 "hide_cursor": False, "url": "http://second"},
            ],
            "chromium_flags": [],
        }

        try:
            app_module.detect_monitors = lambda: self.monitors
            app_module.save_config = lambda value: saved_configs.append(value)
            manager = RecordingManager()

            manager.start_all(cfg)
        finally:
            app_module.detect_monitors = original_detect_monitors
            app_module.save_config = original_save_config

        self.assertEqual([item[2]["name"] for item in manager.started],
                         ["HDMI-A-1", "HDMI-A-2"])
        self.assertEqual(cfg["screens"][1]["output"], "HDMI-A-2")
        self.assertEqual(len(saved_configs), 1)

    def test_start_all_does_not_start_two_screens_on_same_explicit_output(self):
        original_detect_monitors = app_module.detect_monitors

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, dict(screen), monitor))

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

            def _ensure_watcher(self):
                pass

        cfg = {
            "screens": [
                {"name": "First", "enabled": True, "output": "HDMI-A-1",
                 "hide_cursor": False, "url": "http://first"},
                {"name": "Second", "enabled": True, "output": "HDMI-A-1",
                 "hide_cursor": False, "url": "http://second"},
            ],
            "chromium_flags": [],
        }

        try:
            app_module.detect_monitors = lambda: self.monitors
            manager = RecordingManager()

            manager.start_all(cfg)
        finally:
            app_module.detect_monitors = original_detect_monitors

        self.assertEqual(manager.started[0][2]["name"], "HDMI-A-1")
        self.assertIsNone(manager.started[1][2])


if __name__ == "__main__":
    unittest.main()

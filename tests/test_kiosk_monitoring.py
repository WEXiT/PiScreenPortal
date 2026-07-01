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
from app import KioskManager, MaintenanceManager, parse_xrandr_monitors


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

XRANDR_VIRTUAL_SAMPLE = """
Screen 0: minimum 16 x 16, current 5760 x 1080, maximum 32767 x 32767
VIRTUAL1 connected 1920x1080+0+0 (normal left inverted right x axis y axis)
DUMMY0 connected 1920x1080+1920+0 (normal left inverted right x axis y axis)
HEADLESS-1 connected 1920x1080+3840+0 (normal left inverted right x axis y axis)
HDMI-A-1 connected 1920x1080+0+0 (normal left inverted right x axis y axis) 600mm x 340mm
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

    def test_parse_xrandr_monitors_ignores_virtual_outputs(self):
        monitors = parse_xrandr_monitors(XRANDR_VIRTUAL_SAMPLE)

        self.assertEqual([m["name"] for m in monitors], ["HDMI-A-1"])


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

    def test_active_monitors_filters_virtual_mocks(self):
        monitors = [
            {"name": "DUMMY0", "active": True, "width": 1920, "height": 1080},
            {"name": "HDMI-A-1", "active": True, "width": 1920, "height": 1080},
            {"name": "Virtual-1", "active": True, "width": 1920, "height": 1080},
        ]

        active = self.manager._active_monitors(monitors)

        self.assertEqual([m["name"] for m in active], ["HDMI-A-1"])

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


class ReloadTests(unittest.TestCase):
    def test_git_update_stashes_local_changes_before_pull(self):
        original_which = app_module.shutil.which
        commands = []
        head = {"value": "12968f4"}

        manager = MaintenanceManager()

        def fake_git_text(args, timeout=10):
            if args == ["remote", "get-url", "origin"]:
                return "https://github.com/WEXiT/PiScreenPortal.git"
            if args == ["rev-parse", "--short", "HEAD"]:
                return head["value"]
            if args == ["rev-parse", "--verify", "stash@{0}"]:
                return "stashhash"
            return ""

        def fake_run_git(cmd, env=None, timeout=60):
            commands.append(cmd)
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return True, " M install.sh"
            if cmd[:3] == ["git", "stash", "push"]:
                return True, "Saved working directory and index state"
            if cmd[:2] == ["git", "pull"]:
                head["value"] = "a246407"
                return True, "Updating 12968f4..a246407"
            return True, ""

        try:
            app_module.shutil.which = lambda name: "/usr/bin/git"
            manager._git_text = fake_git_text
            manager._run_git = fake_run_git
            manager._reboot_later = lambda *args, **kwargs: None

            result = manager.update_from_git_and_reboot()
        finally:
            app_module.shutil.which = original_which

        self.assertTrue(result["ok"])
        self.assertTrue(result["local_changes_stashed"])
        self.assertEqual(result["stash_ref"], "stashhash")
        self.assertIn(["git", "status", "--porcelain"], commands)
        self.assertTrue(any(cmd[:3] == ["git", "stash", "push"]
                            for cmd in commands))
        self.assertTrue(any(cmd[:2] == ["git", "pull"] for cmd in commands))
        self.assertFalse(any(cmd[:3] == ["git", "stash", "pop"]
                             for cmd in commands))

    def test_start_screen_uses_managed_window_flags(self):
        original_popen = app_module.subprocess.Popen
        captured = []

        class FakeProcess:
            pid = 1234

            def poll(self):
                return None

        class RecordingManager(KioskManager):
            def _chromium_bin(self):
                return "chromium"

            def _profile_dir(self, idx):
                return f"profile-{idx}"

            def _env(self):
                return {}

        def fake_popen(cmd, **kwargs):
            captured.append(cmd)
            return FakeProcess()

        try:
            app_module.subprocess.Popen = fake_popen
            manager = RecordingManager()
            manager.start_screen(
                0,
                {"name": "Links", "enabled": True, "url": "http://left",
                 "zoom": 1, "reload_interval": 0},
                {"name": "HDMI-A-1", "x": 0, "y": 0,
                 "width": 1920, "height": 1080},
                ["--new-tab", "--window-position=99,99",
                 "--disable-gpu"],
            )
        finally:
            app_module.subprocess.Popen = original_popen

        self.assertIn("--new-window", captured[0])
        self.assertNotIn("--new-tab", captured[0])
        self.assertNotIn("--window-position=99,99", captured[0])
        self.assertIn("--window-position=0,0", captured[0])
        self.assertIn("--ozone-platform=x11", captured[0])
        self.assertIn("--disable-gpu", captured[0])

    def test_start_screen_repositions_x11_window_after_launch(self):
        original_popen = app_module.subprocess.Popen
        original_run = app_module.subprocess.run
        original_which = app_module.shutil.which
        commands = []

        class FakeProcess:
            pid = 4321

            def poll(self):
                return None

        class RecordingManager(KioskManager):
            def _chromium_bin(self):
                return "chromium"

            def _profile_dir(self, idx):
                return f"profile-{idx}"

            def _env(self):
                return {}

        def fake_popen(cmd, **kwargs):
            return FakeProcess()

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            if cmd[:3] == ["xdotool", "search", "--pid"]:
                return SimpleNamespace(returncode=0, stdout=b"777\n", stderr=b"")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        try:
            app_module.subprocess.Popen = fake_popen
            app_module.subprocess.run = fake_run
            app_module.shutil.which = lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
            manager = RecordingManager()
            manager.start_screen(
                0,
                {"name": "Links", "enabled": True, "url": "http://left",
                 "zoom": 1, "reload_interval": 0},
                {"name": "HDMI-A-2", "x": 1920, "y": 0,
                 "width": 1920, "height": 1080},
                [],
            )
        finally:
            app_module.subprocess.Popen = original_popen
            app_module.subprocess.run = original_run
            app_module.shutil.which = original_which

        self.assertIn(["xdotool", "search", "--pid", "4321"], commands)
        self.assertIn(["xdotool", "windowmove", "777", "1920", "0"], commands)
        self.assertIn(["xdotool", "windowsize", "777", "1920", "1080"], commands)
        self.assertIn(["xdotool", "windowraise", "777"], commands)

    def test_window_reposition_falls_back_to_profile_window_search(self):
        original_run = app_module.subprocess.run
        original_which = app_module.shutil.which
        original_window_ids = app_module._chromium_window_ids
        original_window_pid = app_module._window_pid
        original_has_marker = app_module._pid_has_profile_marker
        commands = []

        class RecordingManager(KioskManager):
            def _env(self):
                return {}

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            if cmd[:3] == ["xdotool", "search", "--pid"]:
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"")
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        try:
            app_module.subprocess.run = fake_run
            app_module.shutil.which = lambda name: "/usr/bin/xdotool" if name == "xdotool" else None
            app_module._chromium_window_ids = lambda env: ["700", "701"]
            app_module._window_pid = lambda wid, env: {"700": 111, "701": 222}[wid]
            app_module._pid_has_profile_marker = lambda pid, marker: pid == 222 and marker == "chromium-profile-1"

            manager = RecordingManager()
            manager._position_screen_window(
                1,
                4321,
                {"name": "HDMI-A-1", "x": 0, "y": 0,
                 "width": 1920, "height": 1080},
            )
        finally:
            app_module.subprocess.run = original_run
            app_module.shutil.which = original_which
            app_module._chromium_window_ids = original_window_ids
            app_module._window_pid = original_window_pid
            app_module._pid_has_profile_marker = original_has_marker

        self.assertIn(["xdotool", "windowmove", "701", "0", "0"], commands)
        self.assertIn(["xdotool", "windowsize", "701", "1920", "1080"], commands)
        self.assertNotIn(["xdotool", "windowmove", "700", "0", "0"], commands)

    def test_reload_targets_only_kiosk_profile_windows(self):
        original_which = app_module.shutil.which
        original_window_ids = app_module._chromium_window_ids
        original_window_pid = app_module._window_pid
        original_has_profile = app_module._pid_has_kiosk_profile
        original_run = app_module.subprocess.run
        sent = []

        def fake_run(cmd, **kwargs):
            if cmd[:3] == ["xdotool", "key", "--window"]:
                sent.append(cmd[3])
            return SimpleNamespace(returncode=0)

        try:
            app_module.shutil.which = lambda name: "/usr/bin/xdotool"
            app_module._chromium_window_ids = lambda env: ["101", "102", "103"]
            app_module._window_pid = lambda wid, env: {
                "101": 1001,
                "102": 1002,
                "103": 1003,
            }[wid]
            app_module._pid_has_kiosk_profile = lambda pid: pid in (1001, 1003)
            app_module.subprocess.run = fake_run

            ok = app_module._reload_chromium_windows()
        finally:
            app_module.shutil.which = original_which
            app_module._chromium_window_ids = original_window_ids
            app_module._window_pid = original_window_pid
            app_module._pid_has_kiosk_profile = original_has_profile
            app_module.subprocess.run = original_run

        self.assertTrue(ok)
        self.assertEqual(sent, ["101", "103"])


class WatcherTests(unittest.TestCase):
    def test_watch_tick_waits_for_hotplug_layout_to_stabilize(self):
        class RecordingManager(KioskManager):
            HOTPLUG_STABLE_SECONDS = 4.0

            def __init__(self):
                super().__init__()
                self.restart_count = 0

            def start_all(self, cfg=None):
                self.restart_count += 1
                with self.lock:
                    self._last_monitor_layout = self._layout_signature(
                        app_module.detect_monitors())
                    self._pending_monitor_layout = None
                    self._pending_monitor_layout_since = 0.0

        manager = RecordingManager()
        two_monitors = parse_xrandr_monitors(XRANDR_SAMPLE)
        one_monitor = [two_monitors[0]]
        cfg = {"restart_on_crash": False, "screens": [], "chromium_flags": []}
        original_detect_monitors = app_module.detect_monitors
        current_monitors = {"value": two_monitors}

        try:
            app_module.detect_monitors = lambda: current_monitors["value"]
            with manager.lock:
                manager._desired_running = True
                manager._last_monitor_layout = manager._layout_signature(two_monitors)

            current_monitors["value"] = one_monitor
            manager._watch_tick(cfg, one_monitor, now=10.0)
            self.assertEqual(manager.restart_count, 0)

            current_monitors["value"] = two_monitors
            manager._watch_tick(cfg, two_monitors, now=15.0)
            self.assertEqual(manager.restart_count, 0)

            manager._watch_tick(cfg, two_monitors, now=20.0)
        finally:
            app_module.detect_monitors = original_detect_monitors

        self.assertEqual(manager.restart_count, 1)

    def test_watch_tick_does_not_respawn_two_screens_on_same_explicit_output(self):
        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append((idx, monitor))

        manager = RecordingManager()
        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)
        cfg = {
            "restart_on_crash": True,
            "screens": [
                {"name": "Links", "enabled": True, "output": "HDMI-A-1",
                 "hide_cursor": False, "url": "http://left"},
                {"name": "New screen", "enabled": True, "output": "HDMI-A-1",
                 "hide_cursor": False, "url": "http://right"},
            ],
            "chromium_flags": [],
        }
        with manager.lock:
            manager._desired_running = True
            manager._last_monitor_layout = manager._layout_signature(monitors)

        manager._watch_tick(cfg, monitors)

        self.assertEqual(manager.started[0][1]["name"], "HDMI-A-1")
        self.assertIsNone(manager.started[1][1])

    def test_watch_tick_respawns_under_apply_lock(self):
        class RecordingLock:
            def __init__(self):
                self.depth = 0

            def __enter__(self):
                self.depth += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                self.depth -= 1

            @property
            def locked(self):
                return self.depth > 0

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.apply_lock = RecordingLock()
                self.started_under_lock = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started_under_lock.append(self.apply_lock.locked)

        manager = RecordingManager()
        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)
        cfg = {
            "restart_on_crash": True,
            "screens": [
                {"name": "Links", "enabled": True, "output": "HDMI-A-2",
                 "hide_cursor": False, "url": "http://left"},
            ],
            "chromium_flags": [],
        }
        with manager.lock:
            manager._desired_running = True
            manager._last_monitor_layout = manager._layout_signature(monitors)

        manager._watch_tick(cfg, monitors)

        self.assertEqual(manager.started_under_lock, [True])


if __name__ == "__main__":
    unittest.main()

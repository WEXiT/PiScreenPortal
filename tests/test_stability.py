import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_kiosk_monitoring  # noqa: F401  (installiert ggf. den Flask-Stub)
import app as app_module
from app import KioskManager, PresentationManager, parse_xrandr_monitors
from test_kiosk_monitoring import XRANDR_SAMPLE

HAS_REAL_FLASK = hasattr(app_module.app, "test_client")


class TempConfigMixin:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for name, value in (
            ("CONFIG_FILE", base / "config.json"),
            ("CONFIG_BACKUP_FILE", base / "config.json.bak"),
            ("DISPLAY_CACHE_FILE", base / "display_cache.json"),
            ("LOG_FILE", base / "kiosk.log"),
        ):
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        cache_patcher = patch.object(app_module, "_config_cache", None)
        cache_patcher.start()
        self.addCleanup(cache_patcher.stop)


class ConfigNormalizationTests(unittest.TestCase):
    def test_screen_values_are_sanitized(self):
        screen = app_module.normalize_screen({
            "url": "example.com/board",
            "zoom": None,
            "rotation": "sideways",
            "reload_interval": -5,
            "resolution": "1920x1080; rm -rf /",
        }, 1)

        self.assertEqual(screen["url"], "https://example.com/board")
        self.assertEqual(screen["zoom"], 1.0)
        self.assertEqual(screen["rotation"], "normal")
        self.assertEqual(screen["reload_interval"], 0)
        self.assertEqual(screen["resolution"], "")
        self.assertEqual(screen["name"], "Screen 2")
        self.assertTrue(screen["enabled"])

    def test_local_urls_get_http_and_existing_schemes_are_kept(self):
        self.assertEqual(app_module.normalize_url("localhost:3000"),
                         "http://localhost:3000")
        self.assertEqual(app_module.normalize_url("192.168.1.5/dash"),
                         "http://192.168.1.5/dash")
        self.assertEqual(app_module.normalize_url("file:///home/pi/a.html"),
                         "file:///home/pi/a.html")
        self.assertEqual(app_module.normalize_url(""), "about:blank")

    def test_keyring_is_disabled_by_default(self):
        cfg = app_module.normalize_config({"screens": []})
        self.assertTrue(cfg["disable_keyring"])
        self.assertTrue(app_module.DEFAULT_CONFIG["disable_keyring"])
        self.assertIn("--password-store=basic",
                      app_module.normalize_chromium_flags([]))


class ConfigPersistenceTests(TempConfigMixin, unittest.TestCase):
    def test_save_keeps_backup_and_load_falls_back_to_it(self):
        app_module.save_config({"screens": [{"url": "https://first"}]})
        app_module.save_config({"screens": [{"url": "https://second"}]})
        self.assertIn("https://first",
                      app_module.CONFIG_BACKUP_FILE.read_text(encoding="utf-8"))

        # Simulierter Stromausfall: halb geschriebene Datei.
        app_module.CONFIG_FILE.write_text('{"screens": [', encoding="utf-8")
        cfg = app_module.load_config()

        self.assertEqual(cfg["screens"][0]["url"], "https://first")

    def test_load_config_returns_independent_copies(self):
        app_module.save_config({"screens": [{"url": "https://a"}]})
        first = app_module.load_config()
        first["screens"][0]["url"] = "https://mutated"

        self.assertEqual(app_module.load_config()["screens"][0]["url"],
                         "https://a")

    def test_watchdog_binding_does_not_overwrite_newer_user_config(self):
        stale = app_module.normalize_config({"screens": [
            {"name": "A", "url": "https://a", "output": ""},
            {"name": "B", "url": "https://b", "output": ""},
        ]})
        # Nutzer hat inzwischen Bildschirm B auf eine neue URL geaendert.
        app_module.save_config({"screens": [
            {"name": "A", "url": "https://a", "output": ""},
            {"name": "B", "url": "https://new-b", "output": ""},
        ]})

        KioskManager._persist_bindings(stale, {0: "HDMI-A-1", 1: "HDMI-A-2"})

        saved = json.loads(app_module.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["screens"][0]["output"], "HDMI-A-1")
        self.assertEqual(saved["screens"][1]["url"], "https://new-b")
        self.assertEqual(saved["screens"][1]["output"], "")


class PasswordTests(unittest.TestCase):
    def test_plain_password_is_hashed_and_empty_password_keeps_hash(self):
        cfg, error = app_module.validate_config_payload({
            "screens": [],
            "auth": {"enabled": True, "username": "admin", "password": "s3cret"},
        })
        self.assertIsNone(error)
        self.assertNotIn("password", cfg["auth"])
        stored = cfg["auth"]["password_hash"]
        self.assertTrue(app_module.verify_password("s3cret", stored))
        self.assertFalse(app_module.verify_password("wrong", stored))

        updated, error = app_module.validate_config_payload(
            {"screens": [], "auth": {"enabled": True, "username": "admin",
                                     "password": ""}},
            previous=cfg)
        self.assertIsNone(error)
        self.assertEqual(updated["auth"]["password_hash"], stored)

    def test_enabling_auth_without_password_is_rejected(self):
        cfg, error = app_module.validate_config_payload({
            "screens": [],
            "auth": {"enabled": True, "username": "admin", "password": ""},
        })
        self.assertIsNone(cfg)
        self.assertIn("Passwort", error)

    def test_public_config_never_contains_secret(self):
        public = app_module.public_config({
            "auth": {"enabled": True, "username": "admin",
                     "password_hash": app_module.hash_password("x")},
            "screens": [],
        })
        self.assertNotIn("password_hash", json.dumps(public))
        self.assertTrue(public["auth"]["password_set"])


class RotationAndResolutionTests(unittest.TestCase):
    def test_parser_reads_current_rotation(self):
        sample = XRANDR_SAMPLE.replace(
            "HDMI-A-2 connected 1920x1080+0+0 (normal",
            "HDMI-A-2 connected 1080x1920+0+0 left (normal")
        monitors = {m["name"]: m for m in parse_xrandr_monitors(sample)}

        self.assertEqual(monitors["HDMI-A-2"]["rotation"], "left")
        self.assertEqual(monitors["HDMI-A-1"]["rotation"], "normal")

    def _start_on_rotated_monitor(self, rotated_by_us: bool) -> list:
        applied = []

        class RecordingManager(KioskManager):
            def stop_screen(self, idx):
                pass

            def _apply_rotation(self, output, rotation):
                applied.append((output, rotation))

            def _chromium_bin(self):
                return "chromium"

            def _profile_dir(self, idx):
                return f"profile-{idx}"

            def _start_reload_thread(self, idx, interval, pid):
                pass

            def _position_screen_window(self, idx, pid, monitor):
                return True

        rotated = {"name": "HDMI-A-1", "active": True, "x": 0, "y": 0,
                   "width": 1080, "height": 1920, "rotation": "left"}
        normal = dict(rotated, width=1920, height=1080, rotation="normal")
        popen = lambda *a, **k: SimpleNamespace(pid=1, poll=lambda: None)
        manager = RecordingManager()
        if rotated_by_us:
            manager.rotated_outputs.add("HDMI-A-1")
        with (patch.object(app_module.subprocess, "Popen", popen),
              patch.object(app_module, "detect_monitors", lambda: [normal])):
            manager.start_screen(
                0, {"name": "A", "url": "http://a", "rotation": "normal"},
                rotated, [])
        return applied

    def test_switching_back_to_normal_resets_our_rotation(self):
        self.assertEqual(self._start_on_rotated_monitor(True),
                         [("HDMI-A-1", "normal")])

    def test_rotation_configured_in_the_os_is_left_alone(self):
        self.assertEqual(self._start_on_rotated_monitor(False), [])

    def test_layout_repair_uses_configured_resolution(self):
        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)
        for monitor in monitors:
            monitor["active"] = False
            monitor["available_modes"].append({"name": "1280x720", "rates": [60.0]})
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

        cfg = {"screens": [
            {"enabled": True, "output": "HDMI-A-2", "resolution": "1280x720"},
            {"enabled": True, "output": "HDMI-A-1"},
        ]}
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(app_module, "DISPLAY_CACHE_FILE",
                             Path(tmp) / "cache.json"), \
                patch.object(app_module.subprocess, "run", fake_run), \
                patch.object(app_module, "detect_monitors", lambda: monitors):
            KioskManager()._prepare_monitor_layout(monitors, cfg)

        cmd = commands[0]
        first = cmd.index("HDMI-A-2")
        self.assertEqual(cmd[first + 1:first + 3], ["--mode", "1280x720"])


class AssignmentTests(unittest.TestCase):
    def test_single_monitor_still_shows_first_automatic_screen(self):
        saved = []
        one_monitor = [parse_xrandr_monitors(XRANDR_SAMPLE)[0]]
        cfg = {"screens": [
            {"name": "Links", "enabled": True, "output": "", "url": "http://l"},
            {"name": "Rechts", "enabled": True, "output": "", "url": "http://r"},
        ]}
        with patch.object(app_module, "save_config", saved.append):
            assignments = KioskManager()._assign_screens(cfg, one_monitor)

        self.assertEqual(assignments[0]["name"], "HDMI-A-2")
        self.assertIsNone(assignments[1])
        # Unvollstaendige Zuordnung wird nicht dauerhaft gespeichert.
        self.assertEqual(cfg["screens"][0]["output"], "")
        self.assertEqual(saved, [])

    def test_apply_restarts_only_changed_screen(self):
        class LiveProcess:
            pid = 100

            def poll(self):
                return None

        class RecordingManager(KioskManager):
            def __init__(self):
                super().__init__()
                self.started = []

            def start_screen(self, idx, screen, monitor, flags):
                self.started.append(idx)

            def _verify_screen_window(self, idx, monitor, repair=True):
                return True

            def _start_unclutter(self):
                pass

            def _stop_unclutter(self):
                pass

        monitors = parse_xrandr_monitors(XRANDR_SAMPLE)
        old_cfg = app_module.normalize_config({"screens": [
            {"name": "A", "url": "http://a", "output": "HDMI-A-2"},
            {"name": "B", "url": "http://b", "output": "HDMI-A-1"},
        ], "chromium_flags": []})
        manager = RecordingManager()
        manager.processes = {0: LiveProcess(), 1: LiveProcess()}
        manager.process_outputs = {0: "HDMI-A-2", 1: "HDMI-A-1"}
        for idx, screen in enumerate(old_cfg["screens"]):
            manager.launch_signatures[idx] = manager._launch_signature(
                screen, old_cfg["chromium_flags"])

        new_cfg = json.loads(json.dumps(old_cfg))
        new_cfg["screens"][1]["url"] = "http://b-new"
        manager._reconcile_screens(new_cfg, monitors, restart_existing=False)

        self.assertEqual(manager.started, [1])


class KeyringTests(unittest.TestCase):
    def test_policy_writes_marked_overrides_and_removes_only_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            autostart = home / ".config" / "autostart"
            first = app_module.apply_keyring_policy(True, home)
            second = app_module.apply_keyring_policy(True, home)

            self.assertEqual(len(first["changed"]), 3)
            self.assertEqual(second["changed"], [])
            self.assertTrue(app_module.keyring_status(home)["autostart_disabled"])

            foreign = autostart / "gnome-keyring-ssh.desktop"
            foreign.write_text("[Desktop Entry]\nExec=custom\n", encoding="utf-8")
            app_module.apply_keyring_policy(False, home)

            self.assertFalse((autostart / "gnome-keyring-secrets.desktop").exists())
            self.assertTrue(foreign.exists())


class PresentationTests(unittest.TestCase):
    def _start_with(self, proc):
        resumed = threading.Event()
        manager = PresentationManager()
        with (patch.object(app_module.shutil, "which", lambda name: "/usr/bin/uxplay"),
              patch.object(app_module.subprocess, "Popen", lambda *a, **k: proc)):
            ok, _ = manager.start({"presentation": {}}, on_exit=resumed.set)
        return manager, ok, resumed

    def test_kiosk_resumes_when_uxplay_exits_on_its_own(self):
        done = threading.Event()
        proc = SimpleNamespace(pid=5, wait=done.wait, poll=lambda: None)
        manager, ok, resumed = self._start_with(proc)
        self.assertTrue(ok)

        done.set()
        self.assertTrue(resumed.wait(2))
        self.assertIsNone(manager.proc)

    def test_manual_stop_does_not_trigger_resume_callback(self):
        done = threading.Event()
        proc = SimpleNamespace(pid=5, wait=lambda timeout=None: done.wait(),
                               poll=lambda: 0, terminate=done.set, kill=done.set)
        manager, ok, resumed = self._start_with(proc)
        with patch.object(app_module.subprocess, "call", lambda *a, **k: 0):
            manager.stop()

        self.assertFalse(resumed.wait(0.3))


@unittest.skipUnless(HAS_REAL_FLASK, "Flask ist nicht installiert")
class HttpTests(TempConfigMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.client = app_module.app.test_client()

    def test_cross_site_post_is_rejected(self):
        r = self.client.post("/api/action/reboot",
                             headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)

    def test_same_origin_config_roundtrip_hides_password(self):
        payload = app_module.public_config(app_module.load_config())
        payload["auth"] = {"enabled": False, "username": "admin",
                           "password": "topsecret"}
        r = self.client.post("/api/config", json=payload,
                             headers={"Origin": "http://localhost"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))

        body = self.client.get("/api/config").get_data(as_text=True)
        self.assertNotIn("topsecret", body)
        self.assertNotIn("password_hash", body)
        self.assertNotIn("topsecret",
                         app_module.CONFIG_FILE.read_text(encoding="utf-8"))

    def test_login_page_does_not_reveal_username(self):
        app_module.save_config(app_module.normalize_config({
            "screens": [],
            "auth": {"enabled": True, "username": "geheimer-admin",
                     "password_hash": app_module.hash_password("pw")},
        }))
        body = self.client.get("/login").get_data(as_text=True)
        self.assertNotIn("geheimer-admin", body)

        ok = self.client.post("/login", data={"username": "geheimer-admin",
                                              "password": "pw"},
                              headers={"Origin": "http://localhost"})
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(self.client.get("/api/config").status_code, 200)


if __name__ == "__main__":
    unittest.main()

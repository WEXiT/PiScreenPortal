import base64
import hashlib
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_kiosk_monitoring  # noqa: F401  (installs the Flask stub if needed)
import app as app_module
from app import KioskManager

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MONITOR = {"name": "HDMI-A-1", "x": 0, "y": 0, "width": 1920, "height": 1080}


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class NormalizePlaylistTests(unittest.TestCase):
    def test_missing_playlist_is_disabled_and_empty(self):
        screen = app_module.normalize_screen({"url": "example.com"}, 0)
        self.assertEqual(screen["playlist"], {"enabled": False, "items": []})
        self.assertEqual(app_module.active_playlist(screen), [])

    def test_items_are_sanitized(self):
        playlist = app_module.normalize_playlist({
            "enabled": 1,
            "items": [
                {"url": "example.com/a", "duration": 1},
                {"url": "  ", "duration": 30},
                "kaputt",
                {"url": "http://intranet/b", "duration": "abc"},
                {"url": "https://c.example", "duration": 10 ** 9},
                {"url": "https://d.example", "duration": float("nan")},
            ],
        })
        self.assertTrue(playlist["enabled"])
        self.assertEqual(playlist["items"], [
            {"url": "https://example.com/a", "duration": 5},
            {"url": "http://intranet/b", "duration": 60},
            {"url": "https://c.example", "duration": 86400},
            {"url": "https://d.example", "duration": 60},
        ])

    def test_item_count_is_limited(self):
        playlist = app_module.normalize_playlist({
            "enabled": True,
            "items": [{"url": f"https://x{i}.example"} for i in range(80)],
        })
        self.assertEqual(len(playlist["items"]), app_module.PLAYLIST_MAX_ITEMS)

    def test_disabled_playlist_is_not_active(self):
        screen = {"url": "https://a", "playlist": {
            "enabled": False, "items": [{"url": "https://b", "duration": 10}]}}
        self.assertEqual(app_module.active_playlist(screen), [])

    def test_launch_signature_tracks_active_playlist_only(self):
        base = {"url": "https://a", "zoom": 1, "playlist": {
            "enabled": True, "items": [{"url": "https://b", "duration": 10},
                                       {"url": "https://c", "duration": 20}]}}
        changed = json.loads(json.dumps(base))
        changed["playlist"]["items"][1]["duration"] = 30
        disabled_a = json.loads(json.dumps(base))
        disabled_a["playlist"]["enabled"] = False
        disabled_b = json.loads(json.dumps(disabled_a))
        disabled_b["playlist"]["items"].append({"url": "https://d"})

        sig = KioskManager._launch_signature
        self.assertNotEqual(sig(base, []), sig(changed, []))
        self.assertEqual(sig(disabled_a, []), sig(disabled_b, []))


class StartScreenPlaylistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)
        self.commands = []
        self.playlist_calls = []
        test = self

        class FakeProcess:
            pid = 4321

            def poll(self):
                return None

        class RecordingManager(KioskManager):
            def stop_screen(self, idx):
                pass

            def _chromium_bin(self):
                return "chromium"

            def _profile_dir(self, idx):
                return str(test.profile)

            def _env(self):
                return {}

            def _position_screen_window(self, idx, pid, monitor):
                return True

            def _start_playlist_thread(self, idx, items, start, profile_dir):
                test.playlist_calls.append((idx, items, start, profile_dir))

        def fake_popen(cmd, **kwargs):
            self.commands.append(cmd)
            return FakeProcess()

        patcher = patch.object(app_module.subprocess, "Popen", fake_popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.manager = RecordingManager()

    def screen(self, items, enabled=True):
        return {"name": "Lobby", "enabled": True, "url": "https://single",
                "zoom": 1, "reload_interval": 0,
                "playlist": {"enabled": enabled, "items": items}}

    def test_playlist_starts_at_requested_page_with_devtools_port(self):
        (self.profile / app_module.DEVTOOLS_PORT_FILE).write_text("1234\n/x")
        items = [{"url": "https://a", "duration": 10},
                 {"url": "https://b", "duration": 20}]

        self.manager.start_screen(0, self.screen(items), MONITOR,
                                  ["--disable-gpu",
                                   "--remote-debugging-port=9222"],
                                  playlist_start=1)

        cmd = self.commands[0]
        self.assertIn("--app=https://b", cmd)
        # Chromium honours the last occurrence of a repeated switch.
        self.assertEqual(cmd[-1], "--remote-debugging-port=0")
        self.assertLess(cmd.index("--disable-gpu"), len(cmd) - 1)
        self.assertFalse((self.profile / app_module.DEVTOOLS_PORT_FILE).exists())
        self.assertEqual(self.playlist_calls[0][2], 1)
        self.assertEqual([i["url"] for i in self.playlist_calls[0][1]],
                         ["https://a", "https://b"])

    def test_invalid_start_index_falls_back_to_first_page(self):
        items = [{"url": "https://a"}, {"url": "https://b"}]
        self.manager.start_screen(0, self.screen(items), MONITOR, [],
                                  playlist_start=7)
        self.assertIn("--app=https://a", self.commands[0])
        self.assertEqual(self.playlist_calls[0][2], 0)

    def test_single_page_playlist_needs_no_devtools(self):
        self.manager.start_screen(0, self.screen([{"url": "https://only"}]),
                                  MONITOR, [])
        self.assertIn("--app=https://only", self.commands[0])
        self.assertFalse(any(arg.startswith("--remote-debugging-port")
                             for arg in self.commands[0]))

    def test_disabled_playlist_uses_single_url(self):
        items = [{"url": "https://a"}, {"url": "https://b"}]
        self.manager.start_screen(0, self.screen(items, enabled=False),
                                  MONITOR, [])
        self.assertIn("--app=https://single", self.commands[0])
        self.assertFalse(any(arg.startswith("--remote-debugging-port")
                             for arg in self.commands[0]))


class FakeDevTools:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.received = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.sock.close()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    @staticmethod
    def _frame(opcode, payload, fin=True):
        header = bytearray([(0x80 if fin else 0) | opcode])
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += struct.pack("!H", n)
        else:
            header.append(127)
            header += struct.pack("!Q", n)
        return bytes(header) + payload

    @staticmethod
    def _read_client_frame(conn):
        def exact(n):
            buf = b""
            while len(buf) < n:
                chunk = conn.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError
                buf += chunk
            return buf
        b1, b2 = exact(2)
        assert b2 & 0x80, "client frames must be masked"
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack("!H", exact(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", exact(8))[0]
        mask = exact(4)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(exact(n)))
        return b1 & 0x0F, data

    def _handle(self, conn):
        with conn:
            conn.settimeout(5)
            request = b""
            while b"\r\n\r\n" not in request:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                request += chunk
            head = request.decode("latin-1")
            path = head.split()[1]
            if path == "/json/list":
                body = json.dumps([
                    {"type": "service_worker", "url": "https://sw",
                     "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/sw/1"},
                    {"type": "page", "url": "https://current",
                     "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/page/ABC"},
                ]).encode()
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                             + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
                return
            self.received.append(("path", path))
            key = [line.split(":", 1)[1].strip() for line in head.split("\r\n")
                   if line.lower().startswith("sec-websocket-key:")][0]
            accept = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
            if self.mode == "bad_accept":
                accept = "falsch"
            conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          "Connection: Upgrade\r\n"
                          f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
            if self.mode == "bad_accept":
                return
            opcode, data = self._read_client_frame(conn)
            msg = json.loads(data)
            self.received.append(("msg", opcode, msg))
            if self.mode == "silent":
                time.sleep(2)
                return
            # The client must skip an event (64-bit length) and answer a ping
            # before the reply, which is fragmented into two frames.
            event = json.dumps({"method": "Page.frameNavigated",
                                "params": {"pad": "x" * 70000}}).encode()
            conn.sendall(self._frame(0x1, event))
            conn.sendall(self._frame(0x9, b"hi"))
            pong_opcode, pong = self._read_client_frame(conn)
            self.received.append(("pong", pong_opcode, pong))
            if self.mode == "error":
                reply = {"id": msg["id"], "error": {"message": "Cannot navigate"}}
            else:
                result = {"frameId": "F"}
                if self.mode == "net_error":
                    result["errorText"] = "net::ERR_NAME_NOT_RESOLVED"
                reply = {"id": msg["id"], "result": result}
            payload = json.dumps(reply).encode()
            conn.sendall(self._frame(0x1, payload[:5], fin=False)
                         + self._frame(0x0, payload[5:]))
            time.sleep(0.1)


class CdpClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.profile = Path(self.tmp.name)

    def server(self, mode="ok"):
        server = FakeDevTools(mode)
        self.addCleanup(server.close)
        (self.profile / app_module.DEVTOOLS_PORT_FILE).write_text(
            f"{server.port}\n/devtools/browser/xyz\n")
        return server

    def test_navigate_sends_page_navigate_and_skips_events(self):
        server = self.server()
        ok, info = app_module._cdp_navigate(self.profile, "https://next")
        self.assertEqual((ok, info), (True, ""))
        self.assertIn(("path", "/devtools/page/ABC"), server.received)
        msgs = [r for r in server.received if r[0] == "msg"]
        self.assertEqual(msgs[0][1], 0x1)
        self.assertEqual(msgs[0][2]["method"], "Page.navigate")
        self.assertEqual(msgs[0][2]["params"], {"url": "https://next"})
        self.assertIn(("pong", 0xA, b"hi"), server.received)

    def test_unreachable_page_is_not_a_control_failure(self):
        self.server("net_error")
        ok, info = app_module._cdp_navigate(self.profile, "https://offline")
        self.assertTrue(ok)
        self.assertEqual(info, "net::ERR_NAME_NOT_RESOLVED")

    def test_protocol_error_is_reported(self):
        self.server("error")
        ok, info = app_module._cdp_navigate(self.profile, "https://x")
        self.assertFalse(ok)
        self.assertIn("Cannot navigate", info)

    def test_invalid_handshake_is_rejected(self):
        self.server("bad_accept")
        ok, info = app_module._cdp_navigate(self.profile, "https://x")
        self.assertFalse(ok)
        self.assertIn("Handshake", info)

    def test_silent_browser_times_out(self):
        self.server("silent")
        started = time.monotonic()
        ok, info = app_module._cdp_navigate(self.profile, "https://x", timeout=0.4)
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_missing_or_stale_port_file(self):
        ok, info = app_module._cdp_navigate(self.profile, "https://x")
        self.assertEqual((ok, info), (False, "DevToolsActivePort fehlt"))
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()  # nothing listens on this port any more
        (self.profile / app_module.DEVTOOLS_PORT_FILE).write_text(f"{port}\n")
        ok, info = app_module._cdp_navigate(self.profile, "https://x", timeout=0.5)
        self.assertFalse(ok)
        (self.profile / app_module.DEVTOOLS_PORT_FILE).write_text("kaputt")
        self.assertIsNone(app_module._devtools_port(self.profile))


class PlaylistThreadTests(unittest.TestCase):
    ITEMS = [{"url": "https://a", "duration": 0.03},
             {"url": "https://b", "duration": 0.03},
             {"url": "https://c", "duration": 0.03}]

    def setUp(self):
        self.calls = []
        self.results = []
        self.fallbacks = []
        self.fallback_result = True
        test = self

        def fake_navigate(profile_dir, url, timeout=None):
            test.calls.append(url)
            return test.results.pop(0) if test.results else (True, "")

        patcher = patch.object(app_module, "_cdp_navigate", fake_navigate)
        patcher.start()
        self.addCleanup(patcher.stop)
        log_patcher = patch.object(app_module, "log", lambda msg: None)
        log_patcher.start()
        self.addCleanup(log_patcher.stop)

        class Manager(KioskManager):
            PLAYLIST_RETRY_SECONDS = 0.01

            def _playlist_fallback_restart(self, idx, stop, start, reason):
                test.fallbacks.append((idx, start, reason))
                return test.fallback_result

        self.manager = Manager()
        self.addCleanup(self.manager._stop_playlist_thread, 0)

    def test_rotates_in_order_and_wraps_around(self):
        self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
        self.assertTrue(wait_until(lambda: len(self.calls) >= 4))
        self.assertEqual(self.calls[:4], ["https://b", "https://c",
                                          "https://a", "https://b"])
        self.assertEqual(self.fallbacks, [])

    def test_stop_ends_rotation(self):
        self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
        self.assertTrue(wait_until(lambda: len(self.calls) >= 1))
        self.manager._stop_playlist_thread(0)
        time.sleep(0.05)
        count = len(self.calls)
        time.sleep(0.15)
        self.assertEqual(len(self.calls), count)
        self.assertNotIn(0, self.manager.playlist_state)

    def test_single_retry_recovers_without_restart(self):
        self.results = [(False, "CDP: weg")]
        self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
        self.assertTrue(wait_until(lambda: len(self.calls) >= 3))
        self.assertEqual(self.calls[:3], ["https://b", "https://b", "https://c"])
        self.assertEqual(self.fallbacks, [])

    def test_double_failure_triggers_restart_at_next_page(self):
        self.results = [(False, "CDP: weg"), (False, "CDP: weg")]
        self.manager._start_playlist_thread(0, self.ITEMS, 1, "/p")
        self.assertTrue(wait_until(lambda: self.fallbacks))
        self.assertEqual(self.fallbacks[0], (0, 2, "CDP: weg"))
        time.sleep(0.1)
        self.assertEqual(len(self.calls), 2)

    def test_rotation_continues_when_restart_is_impossible(self):
        self.fallback_result = False
        self.results = [(False, "x"), (False, "x")]
        self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
        self.assertTrue(wait_until(lambda: len(self.calls) >= 4))
        self.assertEqual(self.calls[:4], ["https://b", "https://b",
                                          "https://b", "https://c"])

    def test_unexpected_exception_does_not_stop_rotation(self):
        def boom(profile_dir, url, timeout=None):
            self.calls.append(url)
            if len(self.calls) == 1:
                raise RuntimeError("unerwartet")
            return True, ""

        with patch.object(app_module, "_cdp_navigate", boom):
            self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
            self.assertTrue(wait_until(lambda: len(self.calls) >= 3))
        self.assertEqual(self.calls[:3], ["https://b", "https://c", "https://a"])

    def test_offline_page_is_logged_only_on_change(self):
        logged = []
        self.results = [(True, "net::ERR_NAME_NOT_RESOLVED"), (True, ""),
                        (True, ""), (True, "net::ERR_NAME_NOT_RESOLVED"),
                        (True, ""), (True, ""), (True, ""), (True, "")]
        with patch.object(app_module, "log", logged.append):
            self.manager._start_playlist_thread(0, self.ITEMS, 0, "/p")
            self.assertTrue(wait_until(lambda: len(self.calls) >= 8))
            self.manager._stop_playlist_thread(0)
        # Page 2 fails, is still down in round two and recovers in round three.
        self.assertEqual(len(logged), 2, logged)
        self.assertIn("Seite 2 nicht erreichbar", logged[0])
        self.assertIn("Seite 2 wieder erreichbar", logged[1])

    def test_status_reports_position(self):
        items = [{"url": "https://a", "duration": 60},
                 {"url": "https://b", "duration": 60}]

        class FakeProcess:
            pid = 99

            def poll(self):
                return None

        self.manager.processes[0] = FakeProcess()
        self.manager._start_playlist_thread(0, items, 1, "/p")
        status = self.manager.status()["0"]["playlist"]
        self.assertEqual(status["index"], 1)
        self.assertEqual(status["count"], 2)
        self.assertEqual(status["url"], "https://b")
        self.assertTrue(55 <= status["seconds_left"] <= 60)
        self.assertEqual(status["error"], "")


class PlaylistFallbackRestartTests(unittest.TestCase):
    def setUp(self):
        self.started = []
        test = self
        cfg = {"chromium_flags": ["--x"], "screens": [{
            "name": "A", "enabled": True, "url": "https://single",
            "playlist": {"enabled": True, "items": [
                {"url": "https://a", "duration": 10},
                {"url": "https://b", "duration": 10}]},
        }]}

        class Manager(KioskManager):
            def start_screen(self, idx, screen, monitor, flags, playlist_start=0):
                test.started.append((idx, monitor["name"], flags, playlist_start))

            def _assign_screens(self, cfg, monitors):
                return {0: MONITOR}

        for name, value in (("load_config", lambda: cfg),
                            ("detect_monitors", lambda: [MONITOR]),
                            ("monitor_query_succeeded", lambda: True),
                            ("log", lambda msg: None)):
            patcher = patch.object(app_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manager = Manager()
        self.manager._desired_running = True

    def test_restarts_screen_at_requested_page(self):
        stop = threading.Event()
        self.assertTrue(self.manager._playlist_fallback_restart(0, stop, 3, "x"))
        self.assertEqual(self.started, [(0, "HDMI-A-1", ["--x"], 1)])

    def test_stopped_thread_does_not_restart(self):
        stop = threading.Event()
        stop.set()
        self.assertTrue(self.manager._playlist_fallback_restart(0, stop, 1, "x"))
        self.assertEqual(self.started, [])

    def test_no_restart_when_kiosk_stopped_or_xrandr_failing(self):
        self.manager._desired_running = False
        self.assertFalse(self.manager._playlist_fallback_restart(
            0, threading.Event(), 1, "x"))
        self.manager._desired_running = True
        with patch.object(app_module, "monitor_query_succeeded", lambda: False):
            self.assertFalse(self.manager._playlist_fallback_restart(
                0, threading.Event(), 1, "x"))
        self.assertEqual(self.started, [])


if __name__ == "__main__":
    unittest.main()

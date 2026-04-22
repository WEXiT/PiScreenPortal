/*
 * PiScreenPortal – Demo backend
 * ---------------------------------------------------------------
 * Intercepts every fetch() call that targets "/api/..." and
 * returns realistic-looking data from an in-memory fake state.
 * No real Raspberry Pi is contacted.
 */
(function () {
  "use strict";

  // --------- Fake state -------------------------------------------------
  const state = {
    cfg: {
      port: 2411,
      auto_start: true,
      restart_on_crash: true,
      chromium_flags: [
        "--kiosk",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
      ],
      auth: { enabled: false, username: "admin", password: "" },
      presentation: {
        airplay_name: "PiScreenPortal",
        resolution: "1920x1080",
        stop_kiosk_while_active: true,
      },
      screens: [
        {
          name: "Lobby display",
          enabled: true,
          url: "https://www.raspberrypi.com",
          output: "HDMI-1",
          rotation: "normal",
          hide_cursor: true,
          reload_interval: 300,
          zoom: 1.0,
        },
        {
          name: "Meeting room",
          enabled: true,
          url: "https://grafana.com",
          output: "HDMI-2",
          rotation: "normal",
          hide_cursor: true,
          reload_interval: 0,
          zoom: 1.1,
        },
        {
          name: "Signage (portrait)",
          enabled: false,
          url: "https://example.com/signage",
          output: "",
          rotation: "right",
          hide_cursor: true,
          reload_interval: 60,
          zoom: 1.0,
        },
      ],
    },
    monitors: [
      { name: "HDMI-1", primary: true,  width: 1920, height: 1080, x: 0,    y: 0 },
      { name: "HDMI-2", primary: false, width: 1920, height: 1080, x: 1920, y: 0 },
    ],
    presentation: { available: true, running: false, started_at: null },
    wifi: {
      current: {
        available: true,
        active: { ssid: "OfficeWiFi", signal: 78 },
      },
      saved: [
        { name: "OfficeWiFi", autoconnect: true },
        { name: "HomeNet",    autoconnect: true },
        { name: "Guest",      autoconnect: false },
      ],
      networks: [
        { ssid: "OfficeWiFi",     signal: 78, security: "WPA2", in_use: true  },
        { ssid: "HomeNet",        signal: 54, security: "WPA2", in_use: false },
        { ssid: "Guest",          signal: 41, security: "--",   in_use: false },
        { ssid: "FRITZ!Box 7590", signal: 32, security: "WPA2", in_use: false },
        { ssid: "Neighbor-5G",    signal: 18, security: "WPA3", in_use: false },
      ],
    },
    startupTime: Date.now(),
    logLines: [
      "[boot] systemd-pi-kiosk.service started",
      "[chromium] launched on HDMI-1 (PID 2134)",
      "[chromium] launched on HDMI-2 (PID 2136)",
      "[watchdog] all screens healthy",
    ],
  };

  // --------- Helpers ----------------------------------------------------
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  const text = (body) =>
    new Response(body, { status: 200, headers: { "Content-Type": "text/plain" } });

  const log = (line) => {
    const ts = new Date().toISOString().slice(11, 19);
    state.logLines.push(`[${ts}] ${line}`);
    if (state.logLines.length > 60) state.logLines.shift();
  };

  const randBetween = (a, b) => (a + Math.random() * (b - a));

  function buildStatus() {
    const upSec = Math.floor((Date.now() - state.startupTime) / 1000) + 3600 * 7;
    const h = Math.floor(upSec / 3600), m = Math.floor((upSec % 3600) / 60);
    const processes = {};
    state.cfg.screens.forEach((s, i) => {
      processes[String(i)] = s.enabled
        ? { running: true,  pid: 2134 + i * 2 }
        : { running: false, pid: null };
    });
    return {
      system: {
        hostname: "pi-kiosk",
        ip: "192.168.1.42",
        cpu_temp: randBetween(42, 58).toFixed(1) + " °C",
        cpu_percent: randBetween(3, 22).toFixed(1) + " %",
        memory: {
          MemTotal: "8.0 GB",
          MemAvailable: (randBetween(5.2, 6.8)).toFixed(1) + " GB",
          SwapTotal: "200 MB",
          SwapFree: "200 MB",
        },
        disk: { total: "64 GB", free: "48 GB", percent: "25 %" },
        uptime: `${h} h ${m} min`,
        model: "Raspberry Pi 5 Model B Rev 1.0",
        kernel: "Linux 6.6.31-v8+ aarch64",
        load_avg: "0.21, 0.18, 0.15",
        time: new Date().toLocaleString(),
      },
      processes,
    };
  }

  // --------- Route table -----------------------------------------------
  async function handle(url, init) {
    const method = (init && init.method) || "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const body = init && init.body ? tryParse(init.body) : null;

    // ----- Config
    if (path === "/api/config" && method === "GET")  return json(state.cfg);
    if (path === "/api/config" && method === "POST") {
      Object.assign(state.cfg, body || {});
      log("config saved");
      return json({ ok: true });
    }
    if (path === "/api/config/import" && method === "POST") {
      if (body && typeof body === "object") {
        Object.assign(state.cfg, body);
        return json({ ok: true });
      }
      return json({ ok: false, error: "invalid" }, 400);
    }

    // ----- Monitors & status
    if (path === "/api/monitors") return json(state.monitors);
    if (path === "/api/status")   return json(buildStatus());
    if (path === "/api/logs")     return text(state.logLines.join("\n"));

    // ----- Actions
    if (path.startsWith("/api/action/") && method === "POST") {
      const act = path.slice("/api/action/".length);
      log(`action: ${act} (demo)`);
      return json({ ok: true, message: `Demo: '${act}' simulated` });
    }

    // ----- Wi-Fi
    if (path === "/api/wifi")               return json(state.wifi);
    if (path === "/api/wifi/connect" && method === "POST") {
      const ssid = body && body.ssid;
      state.wifi.networks.forEach(n => (n.in_use = n.ssid === ssid));
      state.wifi.current.active = { ssid, signal: 72 };
      if (ssid && !state.wifi.saved.some(s => s.name === ssid)) {
        state.wifi.saved.push({ name: ssid, autoconnect: true });
      }
      log(`wifi connected: ${ssid}`);
      return json({ ok: true, message: `Connected to ${ssid}` });
    }
    if (path === "/api/wifi/add" && method === "POST") {
      const ssid = body && body.ssid;
      if (!ssid) return json({ ok: false, error: "ssid missing" }, 400);
      if (!state.wifi.saved.some(s => s.name === ssid)) {
        state.wifi.saved.push({ name: ssid, autoconnect: !!body.autoconnect });
      }
      return json({ ok: true, message: `Saved profile '${ssid}'` });
    }
    if (path === "/api/wifi/forget" && method === "POST") {
      const name = body && body.name;
      state.wifi.saved = state.wifi.saved.filter(s => s.name !== name);
      return json({ ok: true });
    }
    if (path === "/api/wifi/reset" && method === "POST") {
      log("wifi: interface restarted");
      return json({ ok: true });
    }

    // ----- Presentation
    if (path === "/api/presentation/status") return json(state.presentation);
    if (path === "/api/presentation/start" && method === "POST") {
      state.presentation.running = true;
      state.presentation.started_at = Math.floor(Date.now() / 1000);
      log("presentation started (demo)");
      return json({ ok: true, message: "Presentation started (demo)", status: state.presentation });
    }
    if (path === "/api/presentation/stop" && method === "POST") {
      state.presentation.running = false;
      state.presentation.started_at = null;
      log("presentation stopped (demo)");
      return json({ ok: true, status: state.presentation });
    }

    // ----- Unknown API route
    if (path.startsWith("/api/")) {
      return json({ ok: false, error: `Demo: no mock for ${method} ${path}` }, 404);
    }

    // Non-API requests fall through to the real network
    return null;
  }

  function tryParse(b) {
    try { return JSON.parse(b); } catch { return b; }
  }

  // --------- Install fetch interceptor ---------------------------------
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (url.includes("/api/")) {
      // Small artificial delay to feel "real"
      await new Promise(r => setTimeout(r, 80 + Math.random() * 120));
      const res = await handle(url, init || {});
      if (res) return res;
    }
    return realFetch(input, init);
  };

  console.info("%c[PiScreenPortal Demo] Mock API active – no backend required.",
               "color:#ff5722;font-weight:bold");
})();

/*
 * PiScreenPortal – Demo backend
 * ---------------------------------------------------------------
 * Intercepts every fetch() call that targets "/api/..." and
 * returns realistic-looking data from an in-memory fake state.
 * No real Raspberry Pi is contacted.
 *
 * The rest of docs/ is generated from the real web interface by
 * tools/build_demo.py – only this file is maintained by hand.
 */

(function () {
  "use strict";

  const MODES_1080 = [
    { name: "1920x1080", rates: [60, 59.94, 50] },
    { name: "1680x1050", rates: [59.88] },
    { name: "1280x1024", rates: [60.02] },
    { name: "1280x720",  rates: [60, 50] },
    { name: "1024x768",  rates: [60] },
  ];
  const MODES_4K = [
    { name: "3840x2160", rates: [30, 25] },
    { name: "2560x1440", rates: [59.95] },
  ].concat(MODES_1080);

  // --------- Fake state -------------------------------------------------
  const state = {
    version: "9",
    remoteVersion: "9",
    kioskRunning: true,
    restarts: {},
    cfg: {
      port: 2411,
      auto_start: true,
      restart_on_crash: true,
      disable_keyring: true,
      auto_reboot: { enabled: true, mode: "daily", interval_minutes: 1440, time: "05:30" },
      chromium_flags: [
        "--disk-cache-size=104857600",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--password-store=basic",
        "--ozone-platform=x11",
      ],
      auth: { enabled: false, username: "admin", password_set: false },
      presentation: {
        airplay_name: "PiScreenPortal",
        resolution: "1920x1080",
        stop_kiosk_while_active: true,
      },
      screens: [
        { name: "Lobby display", enabled: true, url: "https://www.raspberrypi.com",
          output: "HDMI-A-1", resolution: "", rotation: "normal",
          hide_cursor: true, reload_interval: 300, zoom: 1.0 },
        { name: "Meeting room", enabled: true, url: "https://grafana.com",
          output: "HDMI-A-2", resolution: "1920x1080", rotation: "normal",
          hide_cursor: true, reload_interval: 0, zoom: 1.1 },
        { name: "Signage (portrait)", enabled: false, url: "https://example.com/signage",
          output: "", resolution: "", rotation: "right",
          hide_cursor: true, reload_interval: 60, zoom: 1.0 },
      ],
    },
    monitors: [
      { name: "HDMI-A-1", primary: true, active: true, width: 1920, height: 1080,
        x: 0, y: 0, geometry: "1920x1080+0+0", rotation: "normal",
        mode: "1920x1080", rate: 60, preferred_mode: "1920x1080",
        available_modes: MODES_1080, edid_hash: "demo1" },
      { name: "HDMI-A-2", primary: false, active: true, width: 1920, height: 1080,
        x: 1920, y: 0, geometry: "1920x1080+1920+0", rotation: "normal",
        mode: "1920x1080", rate: 60, preferred_mode: "3840x2160",
        available_modes: MODES_4K, edid_hash: "demo2" },
    ],
    presentation: { available: true, running: false, started_at: null, pid: null },
    wifi: {
      current: { available: true, active: { ssid: "OfficeWiFi", signal: 78 } },
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
    systemUpdates: {
      running: false, mode: "", ok: null, error: "", packages: [], count: 0,
      checked_at: null, installed_at: null, output: "", reboot_required: false,
    },
    power: { wifi_live: "on", wifi_persistent: false, ss_timeout: 600, dpms_enabled: true },
    startupTime: Date.now(),
    logLines: [],
  };

  // --------- Helpers ----------------------------------------------------
  const json = (body, status = 200) =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });

  const text = (body) =>
    new Response(body, { status: 200, headers: { "Content-Type": "text/plain" } });

  const now = () => new Date().toISOString().slice(0, 19).replace("T", " ");

  const log = (line) => {
    state.logLines.push(`[${now()}] ${line}`);
    if (state.logLines.length > 120) state.logLines.shift();
  };

  [
    "Erkannte Monitore: HDMI-A-1=1920x1080+0+0, HDMI-A-2=1920x1080+1920+0",
    "Keyring-Autostart deaktiviert",
    "Starte Bildschirm 0 (Lobby display) auf HDMI-A-1: https://www.raspberrypi.com",
    "Fenster fuer Bildschirm 0 auf HDMI-A-1 positioniert",
    "Starte Bildschirm 1 (Meeting room) auf HDMI-A-2: https://grafana.com",
    "Fenster fuer Bildschirm 1 auf HDMI-A-2 positioniert",
    "unclutter gestartet (Mauszeiger verborgen)",
  ].forEach(log);

  const randBetween = (a, b) => (a + Math.random() * (b - a));
  const clone = (v) => JSON.parse(JSON.stringify(v));

  function assignedOutput(screen, idx) {
    const active = state.monitors.filter(m => m.active);
    if (screen.output) return active.some(m => m.name === screen.output) ? screen.output : "";
    const used = new Set(state.cfg.screens
      .filter((s, i) => i !== idx && s.enabled && s.output).map(s => s.output));
    const free = active.find(m => !used.has(m.name));
    return free ? free.name : "";
  }

  function buildProcesses() {
    const processes = {};
    if (!state.kioskRunning || state.presentation.running) return processes;
    const taken = new Set();
    state.cfg.screens.forEach((s, i) => {
      if (!s.enabled) return;
      const output = assignedOutput(s, i);
      if (!output || taken.has(output)) return;
      taken.add(output);
      processes[String(i)] = {
        pid: 2134 + i * 2 + (state.restarts[i] || 0) * 10,
        running: true,
        output,
        window_visible: true,
      };
    });
    return processes;
  }

  function buildStatus() {
    const upSec = Math.floor((Date.now() - state.startupTime) / 1000) + 3600 * 7;
    const h = Math.floor(upSec / 3600), m = Math.floor((upSec % 3600) / 60);
    return {
      system: {
        hostname: "pi-kiosk",
        ip: "192.168.1.42",
        cpu_temp: randBetween(46, 58).toFixed(1) + " °C",
        cpu_percent: randBetween(3, 22).toFixed(0) + "%",
        memory: { MemTotal: "7812 MB", MemAvailable: Math.round(randBetween(5200, 6300)) + " MB",
                  SwapTotal: "512 MB", SwapFree: "512 MB" },
        disk: { total: "58G", used: "9.1G", free: "46G", percent: "17%" },
        uptime: `up ${h} hours, ${m} minutes`,
        model: "Raspberry Pi 5 Model B Rev 1.0",
        kernel: "Linux 6.12.25+rpt-rpi-2712 aarch64",
        load_avg: "0.21 0.18 0.15",
        time: now(),
      },
      processes: buildProcesses(),
      monitors: clone(state.monitors),
      kiosk: { desired_running: state.kioskRunning, presentation_running: state.presentation.running },
      version: state.version,
    };
  }

  function applyScreenModes() {
    // Simuliert eine eingestellte Aufloesung auf dem zugeordneten Monitor.
    state.monitors.forEach(mon => {
      const screen = state.cfg.screens.find(s => s.enabled && s.output === mon.name);
      const mode = (screen && screen.resolution) || "1920x1080";
      const [w, h] = mode.split("x").map(Number);
      const rot = (screen && screen.rotation) || "normal";
      const portrait = rot === "left" || rot === "right";
      mon.mode = mode;
      mon.rotation = rot;
      mon.width = portrait ? h : w;
      mon.height = portrait ? w : h;
    });
    let x = 0;
    state.monitors.forEach(mon => {
      mon.x = x; mon.y = 0;
      mon.geometry = `${mon.width}x${mon.height}+${mon.x}+0`;
      x += mon.width;
    });
  }

  function publicConfig() {
    const cfg = clone(state.cfg);
    cfg.auth = { enabled: !!cfg.auth.enabled, username: cfg.auth.username || "admin",
                 password_set: !!cfg.auth.password_set };
    return cfg;
  }

  function storeConfig(body) {
    if (!body || typeof body !== "object" || !Array.isArray(body.screens)) {
      return "Ungültige Config";
    }
    const used = new Set();
    for (const s of body.screens) {
      if (!s.enabled || !s.output) continue;
      if (used.has(s.output)) {
        return `Monitor-Ausgang ${s.output} ist mehreren aktiven Bildschirmen zugewiesen.`;
      }
      used.add(s.output);
    }
    const auth = body.auth || {};
    const passwordSet = !!auth.password || !!(state.cfg.auth && state.cfg.auth.password_set);
    if (auth.enabled && !passwordSet) {
      return "Wenn der Zugangsschutz aktiv ist, müssen Benutzername und Passwort gesetzt sein.";
    }
    const next = clone(body);
    next.auth = { enabled: !!auth.enabled, username: auth.username || "admin", password_set: passwordSet };
    next.screens = next.screens.map((s, i) => ({
      name: s.name || `Screen ${i + 1}`,
      enabled: s.enabled !== false,
      url: s.url || "about:blank",
      output: s.output || "",
      resolution: s.resolution || "",
      rotation: s.rotation || "normal",
      hide_cursor: s.hide_cursor !== false,
      reload_interval: Math.max(0, parseInt(s.reload_interval, 10) || 0),
      zoom: Math.min(5, Math.max(0.25, Number(s.zoom) || 1)),
    }));
    state.cfg = next;
    applyScreenModes();
    return null;
  }

  function buildPower() {
    const p = state.power;
    const wifi_ok = p.wifi_live === "off" && p.wifi_persistent;
    const blanking_ok = p.ss_timeout === 0 && !p.dpms_enabled;
    return {
      overall: (wifi_ok && blanking_ok) ? "ok" : "warn",
      session: "x11",
      wifi_powersave: {
        available: true, iface: "wlan0",
        state: p.wifi_live,
        persistent_disabled: p.wifi_persistent,
        persistent_config_file: "/etc/NetworkManager/conf.d/99-pi-kiosk-powersave.conf",
      },
      screen_blanking: {
        available: true,
        screensaver_timeout: p.ss_timeout,
        dpms_enabled: p.dpms_enabled,
        dpms_reported: true,
        blanking_off: blanking_ok,
      },
    };
  }

  function buildMaintenance() {
    const ar = state.cfg.auto_reboot || {};
    let next = null;
    if (ar.enabled) {
      const n = new Date();
      if (ar.mode === "interval") {
        next = new Date(n.getTime() + (Number(ar.interval_minutes) || 1440) * 60000);
      } else {
        const [h, m] = String(ar.time || "06:00").split(":").map(x => parseInt(x, 10) || 0);
        next = new Date(n);
        next.setHours(h, m, 0, 0);
        if (next <= n) next.setDate(next.getDate() + 1);
      }
    }
    const fmt = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:00`;
    return {
      auto_reboot: ar,
      running: true,
      next_reboot_at: next ? fmt(next) : null,
      next_reboot_in_seconds: next ? Math.floor((next - Date.now()) / 1000) : null,
      last_auto_reboot_at: null,
      version: state.version,
      git: { available: true, remote: "https://github.com/WEXiT/PiScreenPortal.git",
             branch: "main", head: "demo" },
    };
  }

  function buildServices() {
    const procs = Object.values(buildProcesses());
    return {
      session: "x11", user: "admin", display: ":0", wayland_display: "",
      items: [
        { key: "chromium", label: "Chromium", target: "chromium", kind: "kiosk",
          type: "process", installed: true, running: procs.length > 0,
          pids: procs.map(p => p.pid), note: "", warn: null },
        { key: "unclutter", label: "unclutter", target: "unclutter", kind: "cursor",
          type: "process", installed: true, running: state.kioskRunning,
          pids: state.kioskRunning ? [2140] : [], note: "", warn: null },
        { key: "xdotool", label: "xdotool", target: "xdotool", kind: "tool",
          type: "binary", installed: true, running: null, note: "", warn: null },
        { key: "wmctrl", label: "wmctrl", target: "wmctrl", kind: "tool",
          type: "binary", installed: true, running: null, note: "", warn: null },
        { key: "xrandr", label: "xrandr", target: "xrandr", kind: "tool",
          type: "binary", installed: true, running: null, note: "", warn: null },
        { key: "uxplay", label: "UxPlay (AirPlay)", target: "uxplay", kind: "airplay",
          type: "process", installed: true, running: state.presentation.running,
          pids: state.presentation.running ? [3201] : [], note: "", warn: null },
        { key: "nmcli", label: "NetworkManager (nmcli)", target: "nmcli", kind: "wifi",
          type: "binary", installed: true, running: null, note: "", warn: null },
        { key: "avahi", label: "avahi-daemon", target: "avahi-daemon", kind: "airplay",
          type: "systemd", installed: true, running: true, enabled: true, note: "", warn: null },
        { key: "nm_service", label: "NetworkManager (systemd)", target: "NetworkManager",
          kind: "wifi", type: "systemd", installed: true, running: true, enabled: true,
          note: "", warn: null },
        { key: "pi_kiosk", label: "pi-kiosk.service", target: "pi-kiosk", kind: "system",
          type: "systemd", installed: true, running: true, enabled: true, note: "", warn: null },
      ],
    };
  }

  function buildDiagnostics() {
    const procs = buildProcesses();
    const xrandr = ["Screen 0: minimum 16 x 16, current 3840 x 1080, maximum 7680 x 7680"]
      .concat(state.monitors.map(m =>
        `${m.name} connected${m.primary ? " primary" : ""} ${m.geometry}${m.rotation !== "normal" ? " " + m.rotation : ""} (normal left inverted right x axis y axis) 600mm x 340mm\n` +
        m.available_modes.map(mode => `   ${mode.name.padEnd(12)} ${mode.rates.map((r, n) => r.toFixed(2) + (mode.name === m.mode && n === 0 ? "*" : "") + (mode.name === m.preferred_mode && n === 0 ? "+" : "")).join("  ")}`).join("\n")))
      .join("\n");
    return {
      captured_at: now(),
      monitors: clone(state.monitors),
      assignments: state.cfg.screens.map((s, i) => {
        const p = procs[String(i)];
        return {
          screen: s.name, configured_output: s.output, assigned_output: p ? p.output : "",
          current_output: p ? p.output : "", running: !!p, process_running: !!p,
          window_visible: p ? true : null, visible_on_assigned_output: !!p,
        };
      }),
      xrandr,
      chromium: Object.entries(procs).map(([i, p]) =>
        `${p.pid} /usr/lib/chromium/chromium --kiosk --user-data-dir=/home/admin/PiScreenPortal/chromium-profile-${i} --app=${state.cfg.screens[i].url}`
      ).join("\n") || "(no Chromium processes found)",
      log: state.logLines.slice(-100).join("\n"),
    };
  }

  // --------- Route table -----------------------------------------------
  async function handle(url, init) {
    const method = (init && init.method) || "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const query = new URLSearchParams(url.split("?")[1] || "");
    const body = init && init.body ? tryParse(init.body) : null;

    // ----- Config
    if (path === "/api/config" && method === "GET") return json(publicConfig());
    if ((path === "/api/config" || path === "/api/config/import") && method === "POST") {
      const error = storeConfig(body);
      if (error) return json({ ok: false, error }, 400);
      log(path.endsWith("import") ? "Config importiert" : "Config gespeichert");
      return json({ ok: true });
    }
    if (path === "/api/config/export") {
      return new Response(JSON.stringify(publicConfig(), null, 2), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }

    // ----- Monitors & status
    if (path === "/api/monitors") return json(clone(state.monitors));
    if (path === "/api/monitors/identify" && method === "POST") {
      log("Monitore identifizieren: " + state.monitors.map(m => m.name).join(", "));
      flashLayout();
      return json({ ok: true, monitors: state.monitors.map((m, i) => ({
        number: i + 1, output: m.name, screen: "", pid: 4000 + i })) });
    }
    if (path === "/api/status") return json(buildStatus());
    if (path === "/api/logs") {
      return text(state.logLines.join("\n"));
    }
    if (path === "/api/diagnostics") return json(buildDiagnostics());
    if (path === "/api/keyring") {
      return json({ enabled_in_config: state.cfg.disable_keyring,
                    autostart_disabled: state.cfg.disable_keyring,
                    daemon_running: false, chromium_password_store: "basic" });
    }
    const screenRestart = path.match(/^\/api\/screen\/(\d+)\/restart$/);
    if (screenRestart && method === "POST") {
      const idx = Number(screenRestart[1]);
      const screen = state.cfg.screens[idx];
      if (!screen) return json({ ok: false, error: "Unbekannter Bildschirm" }, 400);
      state.restarts[idx] = (state.restarts[idx] || 0) + 1;
      log(`Starte Bildschirm ${idx} (${screen.name}) auf ${assignedOutput(screen, idx)}: ${screen.url}`);
      return json({ ok: true, output: assignedOutput(screen, idx) });
    }

    // ----- Auth (demo has auth disabled, so everyone is "logged in")
    if (path === "/api/auth/status") {
      return json({
        enabled: !!state.cfg.auth.enabled,
        logged_in: true,
        user: state.cfg.auth.enabled ? (state.cfg.auth.username || "admin") : null,
      });
    }
    if (path === "/login" && method === "POST") return json({ ok: true });
    if (path === "/logout") {
      log("Logout (demo: no-op)");
      return json({ ok: true });
    }

    // ----- Power / 24/7 mode
    if (path === "/api/power") return json(buildPower());
    if (path === "/api/power/disable-all" && method === "POST") {
      Object.assign(state.power, { wifi_live: "off", wifi_persistent: true,
                                   ss_timeout: 0, dpms_enabled: false });
      log("24/7 mode applied (demo)");
      return json({
        ok: true,
        steps: [
          { step: "xset s off", ok: true, msg: "OK" },
          { step: "xset -dpms", ok: true, msg: "OK" },
          { step: "xset s noblank", ok: true, msg: "OK" },
          { step: "nmcli modify 'OfficeWiFi' wifi.powersave=2", ok: true, msg: "OK" },
        ],
        status: buildPower(),
      });
    }

    // ----- Maintenance
    if (path === "/api/maintenance/status") return json(buildMaintenance());
    if (path === "/api/maintenance/check-updates" && method === "POST") {
      return json({
        ok: true,
        current_version: state.version,
        remote_version: state.remoteVersion,
        update_available: Number(state.remoteVersion) > Number(state.version),
        local_newer: Number(state.version) > Number(state.remoteVersion),
        current_head: "demo1", remote_head: "demo1",
        checked_at: now(),
      });
    }
    if (path === "/api/maintenance/update" && method === "POST") {
      log("Git-Update erfolgreich (demo1 -> demo1), Reboot geplant");
      return json({ ok: true, before: "demo1", after: "demo1", changed: false,
                    output: "Already up to date.", reboot_scheduled: true,
                    dependencies: "unchanged" });
    }
    if (path === "/api/maintenance/optimize-boot" && method === "POST") {
      log("Boot-Desktop-Optimierung angewendet");
      return json({ ok: true, steps: ["assets", "pcmanfm", "lxpanel", "autostart",
        "wayland-autostart", "keyring"].map(step => ({ step, ok: true, msg: "OK" })) });
    }
    if (path === "/api/maintenance/system-updates/status") {
      return json({ ok: true, ...state.systemUpdates });
    }
    if (path === "/api/maintenance/system-updates/check" && method === "POST") {
      Object.assign(state.systemUpdates, {
        running: false, mode: "scan", ok: true, error: "", checked_at: now(),
        packages: [
          { name: "chromium", source: "bookworm-security", candidate_version: "131.0.6778.85-1~deb12u1", current_version: "130.0.6723.116-1~deb12u1" },
          { name: "raspi-firmware", source: "bookworm", candidate_version: "1:1.20241126-1", current_version: "1:1.20241008-1" },
          { name: "libssl3", source: "bookworm-security", candidate_version: "3.0.15-1~deb12u1", current_version: "3.0.14-1~deb12u2" },
        ],
      });
      state.systemUpdates.count = state.systemUpdates.packages.length;
      return json({ ok: true, ...state.systemUpdates });
    }
    if (path === "/api/maintenance/system-updates/install" && method === "POST") {
      Object.assign(state.systemUpdates, { running: true, mode: "install", ok: null });
      setTimeout(() => Object.assign(state.systemUpdates, {
        running: false, ok: true, packages: [], count: 0, installed_at: now(),
        checked_at: now(), reboot_required: true,
      }), 6000);
      return json({ ok: true, started: true, ...state.systemUpdates });
    }

    // ----- Services & tools status (dashboard card)
    if (path === "/api/services") return json(buildServices());

    // ----- Actions
    if (path.startsWith("/api/action/") && method === "POST") {
      const act = path.slice("/api/action/".length);
      if (act === "start" || act === "restart" || act === "apply") state.kioskRunning = true;
      if (act === "stop") state.kioskRunning = false;
      log(act === "apply" ? "Konfiguration angewendet" : `action: ${act} (demo)`);
      return json({ ok: true });
    }

    // ----- Wi-Fi
    if (path === "/api/wifi") return json(state.wifi);
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
      if (!ssid) return json({ ok: false, error: "SSID fehlt" }, 400);
      if (!state.wifi.saved.some(s => s.name === `pisp-${ssid}`)) {
        state.wifi.saved.push({ name: `pisp-${ssid}`, autoconnect: !!body.autoconnect });
      }
      return json({ ok: true, message: "WLAN gespeichert und verbunden." });
    }
    if (path === "/api/wifi/forget" && method === "POST") {
      const name = body && body.name;
      state.wifi.saved = state.wifi.saved.filter(s => s.name !== name);
      return json({ ok: true });
    }
    if (path === "/api/wifi/reset" && method === "POST") {
      log("wifi: interface restarted");
      return json({ ok: true, message: "WLAN aus- und wieder eingeschaltet" });
    }

    // ----- Presentation
    if (path === "/api/presentation/status") return json(state.presentation);
    if (path === "/api/presentation/start" && method === "POST") {
      state.presentation.running = true;
      state.presentation.started_at = Math.floor(Date.now() / 1000);
      state.presentation.pid = 3201;
      log("Starte Präsentation (UxPlay): uxplay -n PiScreenPortal -fs -s 1920x1080");
      return json({ ok: true, message: "Präsentation gestartet", status: state.presentation });
    }
    if (path === "/api/presentation/stop" && method === "POST") {
      Object.assign(state.presentation, { running: false, started_at: null, pid: null });
      log("Präsentation beendet (demo)");
      return json({ ok: true, status: state.presentation });
    }

    // ----- Unknown API route
    if (path.startsWith("/api/")) {
      return json({ ok: false, error: `Demo: no mock for ${method} ${path}` }, 404);
    }

    // Non-API requests fall through to the real network
    return null;
  }

  function flashLayout() {
    // "Identify" in the demo: briefly highlight the monitor boxes.
    document.querySelectorAll(".layout-map .mon").forEach((el, i) => {
      el.animate([
        { boxShadow: "0 0 0 0 rgba(59,130,246,.9)" },
        { boxShadow: "0 0 0 10px rgba(59,130,246,0)" },
      ], { duration: 900, iterations: 4, delay: i * 120 });
    });
  }

  function tryParse(b) {
    try { return JSON.parse(b); } catch (e) { return b; }
  }

  applyScreenModes();

  // --------- Install fetch interceptor ---------------------------------
  // Match /api/*, /login, /logout - every path our frontend talks to.
  const MOCK_PATHS = /^(https?:\/\/[^/]+)?\/(api\/|login\b|logout\b)/;
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    if (MOCK_PATHS.test(url)) {
      // Small artificial delay to feel "real"
      await new Promise(r => setTimeout(r, 60 + Math.random() * 120));
      const res = await handle(url, init || {});
      if (res) return res;
    }
    return realFetch(input, init);
  };

  console.info("%c[PiScreenPortal Demo] Mock API active – no backend required.",
               "color:#f97316;font-weight:bold");
})();

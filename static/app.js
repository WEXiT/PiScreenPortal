let cfg = null;
let monitors = [];

// Auto-redirect to /login when the session expires mid-session.
// Wraps the global fetch so any 401 on /api/* paths sends the user to /login.
(function installAuthInterceptor() {
  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const r = await origFetch(input, init);
    if (r.status === 401) {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (url.startsWith("/api/") && !url.startsWith("/api/auth/status")) {
        location.href = "/login";
      }
    }
    return r;
  };
})();

// ---------- Tabs ----------
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "wifi") loadWifi();
    if (tab.dataset.tab === "presentation") loadPresentation();
  });
});

// Re-render on language change
document.addEventListener("i18n-applied", () => {
  if (cfg) { renderMonitors(); renderScreens(); }
  refreshStatus();
});

// ---------- Laden ----------
async function load() {
  const [c, m] = await Promise.all([
    fetch("/api/config").then(r => r.json()),
    fetch("/api/monitors").then(r => r.json()),
  ]);
  cfg = c;
  monitors = m;
  renderMonitors();
  renderScreens();
  renderSettings();
  refreshStatus();
}

// ---------- Monitor-Tabelle ----------
function renderMonitors() {
  const tb = document.querySelector("#monitors tbody");
  tb.innerHTML = "";
  if (!monitors.length) {
    tb.innerHTML = `<tr><td colspan="4" class="muted">${t("screens.none_detected")}</td></tr>`;
    return;
  }
  for (const m of monitors) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><code>${m.name}</code></td><td>${m.primary ? t("common.yes") : ""}</td>
      <td>${m.width} x ${m.height}</td><td>${m.x},${m.y}</td>`;
    tb.appendChild(tr);
  }
}

function outputOptions(selected) {
  return [`<option value="">${t("screens.auto")}</option>`]
    .concat(monitors.map(m => `<option value="${m.name}" ${m.name===selected?"selected":""}>${m.name} (${m.width}x${m.height})</option>`))
    .join("");
}

// ---------- Bildschirme ----------
function renderScreens() {
  const host = document.getElementById("screens");
  host.innerHTML = "";
  cfg.screens.forEach((s, i) => {
    const row = document.createElement("div");
    row.className = "screen-row";
    row.innerHTML = `
      <h3>
        <span class="left">${t("screens.label")} ${i+1}
          <input type="text" data-k="name" value="${escape(s.name||'')}" class="inline" placeholder="${t("screens.label_name")}">
        </span>
        <button class="btn-del">${t("common.remove")}</button>
      </h3>
      <label class="check"><input type="checkbox" data-k="enabled" ${s.enabled?"checked":""}> ${t("screens.enabled")}</label>
      <label>${t("screens.output")}
        <select data-k="output">${outputOptions(s.output)}</select>
      </label>
      <label>${t("screens.url")} <input type="url" data-k="url" value="${escape(s.url||"")}"></label>
      <label>${t("screens.rotation")}
        <select data-k="rotation">
          ${["normal","left","right","inverted"].map(r=>`<option ${r===s.rotation?"selected":""}>${r}</option>`).join("")}
        </select>
      </label>
      <label>${t("screens.zoom")} <input type="number" step="0.1" min="0.3" max="3" data-k="zoom" value="${s.zoom||1}"></label>
      <label>${t("screens.reload_interval")} <input type="number" min="0" data-k="reload_interval" value="${s.reload_interval||0}"></label>
      <label class="check"><input type="checkbox" data-k="hide_cursor" ${s.hide_cursor?"checked":""}> ${t("screens.hide_cursor")}</label>
    `;
    row.querySelectorAll("[data-k]").forEach(el => {
      el.addEventListener("change", () => {
        const k = el.dataset.k;
        let v = el.type === "checkbox" ? el.checked :
                el.type === "number" ? parseFloat(el.value) : el.value;
        cfg.screens[i][k] = v;
      });
    });
    row.querySelector(".btn-del").addEventListener("click", () => {
      if (confirm(t("screens.confirm_remove"))) {
        cfg.screens.splice(i, 1);
        renderScreens();
      }
    });
    host.appendChild(row);
  });
}

function escape(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}

// ---------- Einstellungen ----------
function renderSettings() {
  document.getElementById("auto_start").checked = !!cfg.auto_start;
  document.getElementById("restart_on_crash").checked = !!cfg.restart_on_crash;
  document.getElementById("port").value = cfg.port || 2411;
  document.getElementById("chromium_flags").value = (cfg.chromium_flags||[]).join("\n");
  const a = cfg.auth || {};
  document.getElementById("auth_enabled").checked = !!a.enabled;
  document.getElementById("auth_username").value = a.username || "admin";
  document.getElementById("auth_password").value = a.password || "";
}

document.getElementById("add-screen").addEventListener("click", () => {
  cfg.screens.push({
    name: t("screens.new"), enabled: true, url: "https://example.com",
    output: "", rotation: "normal", hide_cursor: true,
    reload_interval: 0, zoom: 1.0,
  });
  renderScreens();
});

document.getElementById("save").addEventListener("click", async () => {
  cfg.auto_start = document.getElementById("auto_start").checked;
  cfg.restart_on_crash = document.getElementById("restart_on_crash").checked;
  cfg.port = parseInt(document.getElementById("port").value, 10) || 2411;
  cfg.chromium_flags = document.getElementById("chromium_flags").value
    .split("\n").map(s=>s.trim()).filter(Boolean);
  cfg.auth = {
    enabled: document.getElementById("auth_enabled").checked,
    username: document.getElementById("auth_username").value || "admin",
    password: document.getElementById("auth_password").value || "",
  };

  const r = await fetch("/api/config", {
    method: "POST", headers: {"Content-Type":"application/json"},
    body: JSON.stringify(cfg)
  }).then(r=>r.json());
  const msg = document.getElementById("msg");
  msg.classList.remove("error");
  if (r.ok) {
    msg.textContent = t("common.applying");
    await fetch("/api/action/restart", {method:"POST"});
    msg.textContent = t("common.saved_restarted");
    loadAuthStatus();
    setTimeout(()=>msg.textContent="", 4000);
  } else {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + (r.error||"?");
  }
});

// ---------- Aktionen ----------
document.querySelectorAll("[data-act]").forEach(b => {
  b.addEventListener("click", async () => {
    const act = b.dataset.act;
    const confirms = {
      "reboot": t("dash.confirm_reboot"),
      "shutdown": t("dash.confirm_shutdown"),
    };
    if (confirms[act] && !confirm(confirms[act])) return;
    b.disabled = true;
    try {
      const r = await fetch("/api/action/" + act, {method:"POST"});
      if (r.status === 401) { location.href = "/login"; return; }
      if (!r.ok) {
        let err = "?";
        try { const j = await r.json(); err = j.error || err; } catch {}
        alert(t("common.error") + ": " + err);
      }
    } catch (e) {
      alert(t("common.error") + ": " + e);
    }
    setTimeout(()=>{ b.disabled = false; refreshStatus(); }, 800);
  });
});

// ---------- Auth (header user + logout) ----------
async function loadAuthStatus() {
  try {
    const s = await fetch("/api/auth/status").then(r => r.json());
    const box = document.getElementById("header-user");
    if (s.enabled && s.logged_in && s.user) {
      document.getElementById("header-user-name").textContent = s.user;
      box.hidden = false;
    } else {
      box.hidden = true;
    }
  } catch (e) {}
}

document.getElementById("btn-logout").addEventListener("click", async () => {
  try {
    await fetch("/logout", {
      method: "POST",
      headers: {"Accept": "application/json"},
    });
  } catch (e) {}
  location.href = "/login";
});

// ---------- Import ----------
document.getElementById("import-file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    const r = await fetch("/api/config/import", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify(data)
    }).then(r=>r.json());
    if (r.ok) { alert(t("settings.import_ok")); location.reload(); }
    else alert(t("common.error")+": "+r.error);
  } catch { alert(t("settings.import_invalid")); }
});

// ---------- Status / Sysinfo ----------
function tile(label, value, cls="") {
  return `<div class="tile ${cls}"><b>${label}</b><span>${value ?? "-"}</span></div>`;
}

function renderSysinfo(sys, target, full=false) {
  const el = document.getElementById(target);
  if (!sys) { el.textContent = "-"; return; }
  const mem = sys.memory || {};
  const disk = sys.disk || {};
  let html = tile(t("system.hostname"), sys.hostname)
    + tile(t("system.ip"), sys.ip)
    + tile(t("system.cpu_temp"), sys.cpu_temp)
    + tile(t("system.cpu_load"), sys.cpu_percent || "-")
    + tile(t("system.ram_free"), mem.MemAvailable || "-")
    + tile(t("system.uptime"), sys.uptime || "-");
  if (full) {
    html += tile(t("system.model"), sys.model || "-")
         + tile(t("system.kernel"), sys.kernel || "-")
         + tile(t("system.load_avg"), sys.load_avg || "-")
         + tile(t("system.ram_total"), mem.MemTotal || "-")
         + tile(t("system.swap"), `${mem.SwapFree||"-"} / ${mem.SwapTotal||"-"}`)
         + tile(t("system.disk_free"), `${disk.free||"-"} (${disk.percent||"-"})`)
         + tile(t("system.disk_total"), disk.total || "-")
         + tile(t("system.time"), sys.time || "-");
  }
  el.innerHTML = html;
}

function renderScreenStatus(procs) {
  const el = document.getElementById("screen-status");
  if (!cfg || !cfg.screens.length) { el.innerHTML = ''; return; }
  let html = "";
  cfg.screens.forEach((s, i) => {
    const p = procs[String(i)];
    const running = p && p.running;
    html += tile(`${s.name || t("screens.label")+" "+(i+1)}`,
      running ? t("screen.running", {pid: p.pid}) : t("screen.inactive"),
      running ? "ok" : "warn");
  });
  el.innerHTML = html;
}

async function refreshStatus() {
  try {
    const s = await fetch("/api/status").then(r=>r.json());
    renderSysinfo(s.system, "sysinfo", false);
    renderSysinfo(s.system, "sysinfo-full", true);
    renderScreenStatus(s.processes || {});
    document.getElementById("status").textContent = JSON.stringify(s.processes, null, 2);
    const log = await fetch("/api/logs").then(r=>r.text());
    const l = document.getElementById("log");
    l.textContent = log || t("system.log_empty");
    l.scrollTop = l.scrollHeight;
  } catch(e) {}
}

// ---------- WLAN ----------
async function loadWifi() {
  const box = document.getElementById("wifi-list");
  const cur = document.getElementById("wifi-current");
  const saved = document.getElementById("wifi-saved");
  box.innerHTML = t("common.scanning");
  cur.innerHTML = t("common.loading");
  saved.innerHTML = t("common.loading");
  try {
    const data = await fetch("/api/wifi").then(r=>r.json());
    if (!data.current.available) {
      cur.innerHTML = `<p class="muted">${t("wifi.na")}</p>`;
      box.innerHTML = "";
      saved.innerHTML = "";
      return;
    }
    if (!data.saved || !data.saved.length) {
      saved.innerHTML = `<p class="muted">${t("wifi.no_saved")}</p>`;
    } else {
      saved.innerHTML = "";
      data.saved.forEach(p => {
        const div = document.createElement("div");
        div.className = "wifi-item";
        div.innerHTML = `
          <div class="info">
            <span class="ssid">${escape(p.name)}</span>
            <span class="meta">${t("wifi.autoconnect")}: ${p.autoconnect ? t("common.yes") : t("common.no")}</span>
          </div>
          <button class="btn">${t("common.remove")}</button>
        `;
        div.querySelector("button").addEventListener("click", async () => {
          if (!confirm(t("wifi.confirm_forget") + ' "' + p.name + '"')) return;
          await fetch("/api/wifi/forget", {
            method:"POST", headers:{"Content-Type":"application/json"},
            body: JSON.stringify({name: p.name})
          });
          loadWifi();
        });
        saved.appendChild(div);
      });
    }
    const act = data.current.active;
    if (act) {
      cur.innerHTML = `<div class="sysinfo">
        ${tile(t("wifi.connected_to"), act.ssid)}
        ${tile(t("wifi.signal"), act.signal ? act.signal + " %" : "-")}
      </div>`;
    } else {
      cur.innerHTML = `<p class="muted">${t("wifi.not_connected")}</p>`;
    }
    if (!data.networks.length) {
      box.innerHTML = `<p class="muted">${t("wifi.no_networks")}</p>`;
      return;
    }
    box.innerHTML = "";
    data.networks.forEach(n => {
      const div = document.createElement("div");
      div.className = "wifi-item" + (n.in_use ? " in-use" : "");
      const sig = parseInt(n.signal) || 0;
      div.innerHTML = `
        <div class="info">
          <span class="ssid">${escape(n.ssid)}</span>
          <span class="meta">
            <span class="signal-bar"><span style="width:${sig}%"></span></span>
            ${sig}% &middot; ${escape(n.security || t("wifi.security_open"))}
            ${n.in_use ? " &middot; " + t("wifi.active") : ""}
          </span>
        </div>
        <button class="btn ${n.in_use?'':'primary'}">${n.in_use ? t("wifi.reconnect") : t("wifi.connect")}</button>
      `;
      div.querySelector("button").addEventListener("click", () => openWifiModal(n));
      box.appendChild(div);
    });
  } catch(e) {
    box.innerHTML = `<p class="muted">${t("common.error")}: `+e+'</p>';
  }
}

document.getElementById("wifi-add-btn").addEventListener("click", async () => {
  const ssid = document.getElementById("wifi-add-ssid").value.trim();
  const password = document.getElementById("wifi-add-password").value;
  const hidden = document.getElementById("wifi-add-hidden").checked;
  const autoconnect = document.getElementById("wifi-add-autoconnect").checked;
  const msg = document.getElementById("wifi-add-msg");
  if (!ssid) { msg.textContent = t("wifi.ssid_missing"); return; }
  msg.textContent = t("common.loading");
  try {
    const r = await fetch("/api/wifi/add", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ssid, password, hidden, autoconnect})
    }).then(r=>r.json());
    msg.textContent = r.message || (r.ok ? t("common.saved") : t("common.error"));
    if (r.ok) {
      document.getElementById("wifi-add-ssid").value = "";
      document.getElementById("wifi-add-password").value = "";
      document.getElementById("wifi-add-hidden").checked = false;
      setTimeout(loadWifi, 1500);
    }
  } catch(e) {
    msg.textContent = t("common.error") + ": " + e;
  }
});

document.getElementById("wifi-rescan").addEventListener("click", loadWifi);
document.getElementById("wifi-reset").addEventListener("click", async () => {
  if (!confirm(t("wifi.confirm_reset"))) return;
  await fetch("/api/wifi/reset", {method:"POST"});
  setTimeout(loadWifi, 3000);
});

// ---------- WiFi Modal ----------
function openWifiModal(n) {
  const modal = document.getElementById("wifi-modal");
  document.getElementById("wifi-modal-ssid").textContent = n.ssid;
  document.getElementById("wifi-password").value = "";
  document.getElementById("wifi-modal-msg").textContent = "";
  modal.hidden = false;
  document.getElementById("wifi-password").focus();
  const isOpen = !n.security || n.security === "--" || n.security.toLowerCase() === "open";
  document.getElementById("wifi-password").disabled = isOpen;

  document.getElementById("wifi-cancel").onclick = () => { modal.hidden = true; };
  document.getElementById("wifi-connect").onclick = async () => {
    const pw = document.getElementById("wifi-password").value;
    const msg = document.getElementById("wifi-modal-msg");
    msg.textContent = t("wifi.connecting");
    try {
      const r = await fetch("/api/wifi/connect", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ssid:n.ssid, password:pw}),
      }).then(r=>r.json());
      if (r.ok) {
        msg.textContent = t("wifi.connected");
        setTimeout(() => { modal.hidden = true; loadWifi(); }, 1500);
      } else {
        msg.textContent = t("common.error") + ": " + (r.message || r.error || "?");
      }
    } catch(e) {
      msg.textContent = t("common.error") + ": " + e;
    }
  };
}

// ---------- Präsentation ----------
function renderPresSettings() {
  const p = (cfg && cfg.presentation) || {};
  document.getElementById("pres-name").value = p.airplay_name || "PiScreenPortal";
  document.getElementById("pres-resolution").value = p.resolution || "1920x1080";
  document.getElementById("pres-stop-kiosk").checked = p.stop_kiosk_while_active !== false;
  document.getElementById("pres-name-hint").textContent = p.airplay_name || "PiScreenPortal";
}

async function loadPresentation() {
  renderPresSettings();
  try {
    const s = await fetch("/api/presentation/status").then(r => r.json());
    renderPresStatus(s);
  } catch(e) {}
}

function renderPresStatus(s) {
  const box = document.getElementById("pres-status-box");
  let html = tile(t("pres.installed"), s.available ? t("common.yes") : t("common.no"), s.available ? "ok" : "warn");
  html += tile(t("pres.status"), s.running ? t("pres.status_active") : t("pres.status_stopped"), s.running ? "ok" : "");
  if (s.running && s.started_at) {
    const secs = Math.floor(Date.now()/1000 - s.started_at);
    const mins = Math.floor(secs/60);
    html += tile(t("pres.uptime"), mins>0 ? `${mins} min ${secs%60} s` : `${secs} s`);
  }
  box.innerHTML = html;
}

// Präsentations-Buttons
document.getElementById("pres-start").addEventListener("click", async () => {
  // Einstellungen vorher speichern, damit sie beim Start verwendet werden
  await savePresSettings();
  const msg = document.getElementById("pres-msg");
  msg.textContent = t("pres.starting");
  const r = await fetch("/api/presentation/start", {method:"POST"}).then(r=>r.json());
  msg.textContent = r.message || (r.ok ? t("common.saved") : t("common.error"));
  renderPresStatus(r.status || {});
});

document.getElementById("pres-stop").addEventListener("click", async () => {
  const msg = document.getElementById("pres-msg");
  msg.textContent = t("pres.stopping");
  const r = await fetch("/api/presentation/stop", {method:"POST"}).then(r=>r.json());
  msg.textContent = t("pres.stopped_running");
  renderPresStatus(r.status || {});
});

async function savePresSettings() {
  if (!cfg.presentation) cfg.presentation = {};
  cfg.presentation.airplay_name = document.getElementById("pres-name").value || "PiScreenPortal";
  cfg.presentation.resolution = document.getElementById("pres-resolution").value;
  cfg.presentation.stop_kiosk_while_active = document.getElementById("pres-stop-kiosk").checked;
  await fetch("/api/config", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(cfg)
  });
  document.getElementById("pres-name-hint").textContent = cfg.presentation.airplay_name;
}

["pres-name","pres-resolution","pres-stop-kiosk"].forEach(id => {
  document.getElementById(id).addEventListener("change", savePresSettings);
});

// Präsentations-Status im Dashboard refresh
async function refreshPresentation() {
  try {
    const s = await fetch("/api/presentation/status").then(r => r.json());
    if (document.getElementById("tab-presentation").classList.contains("active")) {
      renderPresStatus(s);
    }
  } catch(e) {}
}

// ---------- Services & tools ----------
async function loadServices() {
  const host = document.getElementById("services-list");
  const sessEl = document.getElementById("services-session");
  try {
    const d = await fetch("/api/services").then(r => r.json());
    renderServices(d, host, sessEl);
  } catch (e) {
    host.textContent = t("common.error") + ": " + e;
  }
}

function renderServices(d, host, sessEl) {
  const sess = d.session || "unknown";
  sessEl.innerHTML = `${t("svc.session")}
      <span class="session-chip ${escape(sess)}">${escape(sess)}</span>`;

  host.innerHTML = "";
  (d.items || []).forEach(it => {
    const row = document.createElement("div");

    // Status-Klasse bestimmen
    let cls = "idle";
    let stateText = t("svc.idle");

    if (!it.installed) {
      cls = "bad";
      stateText = t("svc.missing");
    } else if (it.warn) {
      cls = "warn";
      stateText = t("svc.installed");
    } else if (it.type === "binary") {
      cls = "ok";
      stateText = t("svc.installed");
    } else if (it.running === true) {
      cls = "ok";
      stateText = t("svc.running");
      if (it.pids && it.pids.length) {
        stateText += " (" + it.pids.length + ")";
      }
    } else if (it.type === "systemd" && it.enabled) {
      cls = "warn";
      stateText = t("svc.stopped");
    } else {
      cls = "idle";
      stateText = it.type === "systemd"
        ? t("svc.stopped")
        : t("svc.idle");
    }

    row.className = "svc " + cls;
    row.innerHTML = `
      <span class="svc-dot" aria-hidden="true"></span>
      <div class="svc-main">
        <div class="svc-title">
          <span class="svc-label">${escape(it.label)}</span>
          <span class="svc-target">${escape(it.target)}</span>
        </div>
        ${it.warn
          ? `<div class="svc-warn">${escape(it.warn)}</div>`
          : (it.note
              ? `<div class="svc-note">${escape(it.note)}</div>`
              : "")}
      </div>
      <span class="svc-state">${stateText}</span>
    `;
    host.appendChild(row);
  });
}

document.getElementById("services-refresh").addEventListener("click", loadServices);

// ---------- Energy / 24/7 mode ----------
async function loadPower() {
  const list = document.getElementById("power-list");
  const badge = document.getElementById("power-overall");
  try {
    const d = await fetch("/api/power").then(r => r.json());
    renderPower(d, list, badge);
  } catch (e) {
    list.textContent = t("common.error") + ": " + e;
  }
}

function renderPower(d, list, badge) {
  // Gesamtbewertung
  const overall = d.overall || "idle";
  const badgeTxt = overall === "ok"   ? t("power.state_ok") :
                   overall === "warn" ? t("power.state_warn") :
                                        t("svc.idle");
  badge.textContent = badgeTxt;
  badge.className = "svc-state"; // basisklasse
  // Badge-Farbe an svc-Logik angleichen: wir nutzen die parent-.svc-Klassen-Tricks
  // daher setzen wir den Span in einem zusätzlichen Wrapper:
  badge.parentElement.classList.remove("power-ok","power-warn","power-idle");
  badge.parentElement.classList.add("power-" + overall);

  // Einzelne Zeilen
  list.innerHTML = "";

  // 1) WLAN-Powersave
  const wp = d.wifi_powersave || {};
  {
    const row = document.createElement("div");
    let cls, state;
    if (!wp.available) {
      cls = "idle";
      state = t("svc.missing");
    } else if (wp.state === "off" && wp.persistent_disabled) {
      cls = "ok"; state = t("power.state_ok");
    } else if (wp.state === "off") {
      cls = "warn"; state = t("power.live_only");
    } else {
      cls = "bad"; state = t("power.state_bad");
    }
    const note = wp.available
      ? `${t("power.iface")} <code>${escape(wp.iface||"?")}</code> &middot; ${t("power.live")}: <b>${escape(wp.state||"?")}</b> &middot; ${t("power.persistent")}: <b>${wp.persistent_disabled ? t("power.off") : t("power.on")}</b>`
      : escape(wp.reason || "-");
    row.className = "svc " + cls;
    row.innerHTML = `
      <span class="svc-dot"></span>
      <div class="svc-main">
        <div class="svc-title"><span class="svc-label">${t("power.wifi_powersave")}</span></div>
        <div class="svc-note">${note}</div>
      </div>
      <span class="svc-state">${state}</span>
    `;
    list.appendChild(row);
  }

  // 2) Screen-Blanking (Screensaver + DPMS)
  const sb = d.screen_blanking || {};
  {
    const row = document.createElement("div");
    let cls, state;
    if (!sb.available) {
      cls = "idle";
      state = sb.reason || t("svc.missing");
    } else if (sb.blanking_off) {
      cls = "ok"; state = t("power.state_ok");
    } else {
      cls = "warn"; state = t("power.state_warn");
    }
    const note = sb.available
      ? `${t("power.screensaver")}: <b>${sb.screensaver_timeout === 0 ? t("power.off") : (sb.screensaver_timeout + "s")}</b> &middot; DPMS: <b>${sb.dpms_enabled ? t("power.on") : t("power.off")}</b>`
      : escape(sb.reason || "-");
    row.className = "svc " + cls;
    row.innerHTML = `
      <span class="svc-dot"></span>
      <div class="svc-main">
        <div class="svc-title"><span class="svc-label">${t("power.screen_blanking")}</span></div>
        <div class="svc-note">${note}</div>
      </div>
      <span class="svc-state">${state}</span>
    `;
    list.appendChild(row);
  }
}

document.getElementById("power-refresh").addEventListener("click", loadPower);

document.getElementById("power-force").addEventListener("click", async () => {
  if (!confirm(t("power.confirm_force"))) return;
  const btn = document.getElementById("power-force");
  const msg = document.getElementById("power-msg");
  btn.disabled = true;
  msg.classList.remove("error");
  msg.textContent = t("power.applying");
  try {
    const r = await fetch("/api/power/disable-all", {method: "POST"});
    const j = await r.json();
    if (j.ok) {
      msg.textContent = t("power.applied_ok");
    } else {
      msg.classList.add("error");
      const failed = (j.steps || []).filter(s => !s.ok)
        .map(s => `${s.step}: ${s.msg}`).join(" | ");
      msg.textContent = t("power.applied_partial") + " " + failed;
    }
    renderPower(j.status || {}, document.getElementById("power-list"),
                document.getElementById("power-overall"));
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
  } finally {
    btn.disabled = false;
    setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 8000);
  }
});

// ---------- Init ----------
setInterval(refreshStatus, 5000);
setInterval(refreshPresentation, 5000);
setInterval(loadServices, 15000);
setInterval(loadPower, 30000);
load();
loadAuthStatus();
loadServices();
loadPower();

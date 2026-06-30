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
function activateTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  const panel = document.getElementById("tab-" + name);
  if (!tab || !panel) return;

  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
  tab.classList.add("active");
  panel.classList.add("active");

  if (name === "wifi") loadWifi();
  if (name === "presentation") loadPresentation();
  if (name === "diagnostics") loadDiagnostics();
  if (name === "settings") onSettingsOpen();
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

const brandHome = document.getElementById("brand-home");
if (brandHome) brandHome.addEventListener("click", () => activateTab("dashboard"));

// Re-render on language change
document.addEventListener("i18n-applied", () => {
  if (cfg) { renderMonitors(); renderScreens(); }
  refreshStatus();
  loadServices();
  loadPower();
  loadMaintenanceStatus();
  loadSystemUpdateStatus();
  if (document.getElementById("tab-diagnostics").classList.contains("active")) {
    loadDiagnostics();
  }
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
  const opts = [`<option value="">${t("screens.auto")}</option>`]
    .concat(monitors.map(m => `<option value="${escape(m.name)}" ${m.name===selected?"selected":""}>${escape(m.name)} (${m.width}x${m.height})</option>`));
  if (selected && !monitors.some(m => m.name === selected)) {
    opts.push(`<option value="${escape(selected)}" selected>${escape(selected)} (${t("screens.not_detected")})</option>`);
  }
  return opts.join("");
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

function tMaybe(key, params) {
  const lang = window.I18N.lang;
  const active = window.I18N[lang] || {};
  const fallback = window.I18N.en || {};
  if (Object.prototype.hasOwnProperty.call(active, key) ||
      Object.prototype.hasOwnProperty.call(fallback, key)) {
    return t(key, params);
  }
  return "";
}

// ---------- Einstellungen ----------
function renderSettings() {
  document.getElementById("auto_start").checked = !!cfg.auto_start;
  document.getElementById("restart_on_crash").checked = !!cfg.restart_on_crash;
  document.getElementById("port").value = cfg.port || 2411;
  document.getElementById("chromium_flags").value = (cfg.chromium_flags||[]).join("\n");
  const ar = cfg.auto_reboot || {};
  document.getElementById("auto_reboot_enabled").checked = !!ar.enabled;
  document.getElementById("auto_reboot_mode").value = ar.mode || "daily";
  document.getElementById("auto_reboot_interval").value = ar.interval_minutes || 1440;
  document.getElementById("auto_reboot_time").value = ar.time || "06:00";
  updateAutoRebootFields();
  const a = cfg.auth || {};
  document.getElementById("auth_enabled").checked = !!a.enabled;
  document.getElementById("auth_username").value = a.username || "admin";
  document.getElementById("auth_password").value = a.password || "";
}

function updateAutoRebootFields() {
  const mode = document.getElementById("auto_reboot_mode").value;
  document.getElementById("auto_reboot_interval_wrap").hidden = mode !== "interval";
  document.getElementById("auto_reboot_time_wrap").hidden = mode !== "daily";
}

["auto_reboot_mode", "auto_reboot_enabled"].forEach(id => {
  document.getElementById(id).addEventListener("change", updateAutoRebootFields);
});

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
  cfg.auto_reboot = {
    enabled: document.getElementById("auto_reboot_enabled").checked,
    mode: document.getElementById("auto_reboot_mode").value,
    interval_minutes: parseInt(document.getElementById("auto_reboot_interval").value, 10) || 1440,
    time: document.getElementById("auto_reboot_time").value || "06:00",
  };
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
    await load();
    msg.textContent = t("common.saved_restarted");
    loadAuthStatus();
    loadMaintenanceStatus();
    setTimeout(()=>msg.textContent="", 4000);
  } else {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + (translateBackendMessage(r.error) || "?");
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
        alert(t("common.error") + ": " + (translateBackendMessage(err) || err));
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
    else alert(t("common.error")+": "+(translateBackendMessage(r.error) || "?"));
  } catch { alert(t("settings.import_invalid")); }
});

// ---------- Maintenance ----------
function renderMaintenanceStatus(d) {
  const badge = document.getElementById("maintenance-next");
  const updateStatus = document.getElementById("update-status");
  if (updateStatus && !updateStatus.dataset.scanned) {
    updateStatus.classList.remove("error", "ok");
    updateStatus.textContent = t("maint.version_current", {version: (d && d.version) || "?"});
  }
  const cfgState = (d && d.auto_reboot) || {};
  if (!cfgState.enabled) {
    badge.textContent = t("maint.disabled");
    badge.className = "svc-state";
    return;
  }
  badge.textContent = d.next_reboot_at
    ? t("maint.next_reboot", {time: d.next_reboot_at})
    : t("maint.status_unknown");
  badge.className = "svc-state maint-active";
}

async function loadMaintenanceStatus() {
  try {
    const d = await fetch("/api/maintenance/status").then(r => r.json());
    renderMaintenanceStatus(d);
  } catch (e) {
    document.getElementById("maintenance-next").textContent = t("maint.status_unknown");
  }
}

document.getElementById("maintenance-refresh").addEventListener("click", loadMaintenanceStatus);

function onSettingsOpen() {
  loadMaintenanceStatus();
  scanAppUpdates({auto: true});
  scanSystemUpdates({auto: true});
}

function renderUpdateScan(j) {
  const status = document.getElementById("update-status");
  status.dataset.scanned = "1";
  status.classList.remove("error", "ok");
  if (j.version_missing && j.update_available) {
    status.classList.add("ok");
    status.textContent = t("maint.update_available_commit", {
      current: j.current_head || "?",
      remote: j.remote_head || "?",
    });
  } else if (j.version_missing) {
    status.textContent = t("maint.no_update_commit", {version: j.current_head || "?"});
  } else if (j.update_available) {
    status.classList.add("ok");
    status.textContent = t("maint.update_available", {
      current: j.current_version || "?",
      remote: j.remote_version || "?",
    });
  } else if (j.local_newer) {
    status.textContent = t("maint.local_newer", {
      current: j.current_version || "?",
      remote: j.remote_version || "?",
    });
  } else {
    status.textContent = t("maint.no_update", {version: j.current_version || "?"});
  }
}

async function scanAppUpdates(opts={}) {
  const btn = document.getElementById("scan-updates");
  const msg = document.getElementById("updates-msg");
  const status = document.getElementById("update-status");
  if (btn.disabled) return;
  btn.disabled = true;
  msg.classList.remove("error");
  status.classList.remove("error", "ok");
  msg.textContent = t("maint.scan_running");
  try {
    const r = await fetch("/api/maintenance/check-updates", {method: "POST"});
    const j = await r.json();
    if (j.ok) {
      renderUpdateScan(j);
      msg.textContent = j.update_available ? t("maint.scan_update_found") : t("maint.scan_no_update");
    } else {
      msg.classList.add("error");
      status.classList.add("error");
      status.dataset.scanned = "1";
      status.textContent = t("maint.scan_failed") + " " +
        (translateBackendMessage(j.error) || "?");
      msg.textContent = "";
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
  } finally {
    btn.disabled = false;
    if (!opts.auto) {
      setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 9000);
    }
  }
}

document.getElementById("scan-updates").addEventListener("click", () => scanAppUpdates());

document.getElementById("boot-optimize").addEventListener("click", async () => {
  if (!confirm(t("boot.confirm_optimize"))) return;
  const btn = document.getElementById("boot-optimize");
  const msg = document.getElementById("boot-msg");
  btn.disabled = true;
  msg.classList.remove("error");
  msg.textContent = t("boot.optimize_running");
  try {
    const r = await fetch("/api/maintenance/optimize-boot", {method: "POST"});
    const j = await r.json();
    if (j.ok) {
      msg.textContent = t("boot.optimize_ok");
    } else {
      msg.classList.add("error");
      const failed = (j.steps || []).filter(s => !s.ok)
        .map(s => `${s.step}: ${s.msg}`).join(" | ");
      msg.textContent = t("boot.optimize_failed") + " " + (failed || j.error || "?");
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
  } finally {
    btn.disabled = false;
    setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 9000);
  }
});

document.getElementById("git-update").addEventListener("click", async () => {
  if (!confirm(t("maint.confirm_update"))) return;
  const btn = document.getElementById("git-update");
  const msg = document.getElementById("updates-msg");
  btn.disabled = true;
  msg.classList.remove("error");
  msg.textContent = t("maint.update_running");
  try {
    const r = await fetch("/api/maintenance/update", {method: "POST"});
    const j = await r.json();
    if (j.ok) {
      msg.textContent = j.changed
        ? t("maint.update_ok_changed")
        : t("maint.update_ok_current");
    } else {
      msg.classList.add("error");
      msg.textContent = t("maint.update_failed") + " " +
        (translateBackendMessage(j.error) || "?");
      btn.disabled = false;
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
    btn.disabled = false;
  }
});

function renderSystemUpdates(d) {
  const badge = document.getElementById("system-updates-count");
  const list = document.getElementById("system-updates-list");
  const install = document.getElementById("system-updates-install");
  const msg = document.getElementById("system-updates-msg");
  const packages = (d && d.packages) || [];

  badge.className = "svc-state";
  if (d && d.running) {
    badge.textContent = d.mode === "install"
      ? t("updates.system_installing")
      : t("updates.system_scanning");
    list.innerHTML = `<p class="muted">${badge.textContent}</p>`;
    install.disabled = true;
    return;
  }

  if (d && d.error) {
    badge.textContent = t("common.error");
    badge.classList.add("error");
    list.innerHTML = `<p class="muted error">${escape(translateBackendMessage(d.error) || d.error)}</p>`;
    install.disabled = true;
    return;
  }

  if (!d || d.ok === null || d.checked_at === null) {
    badge.textContent = t("updates.system_unknown");
    list.innerHTML = `<p class="muted">${t("updates.system_not_scanned")}</p>`;
    install.disabled = true;
    return;
  }

  if (!packages.length) {
    badge.textContent = t("updates.system_none");
    list.innerHTML = `<p class="muted">${t("updates.system_no_updates")}</p>`;
    install.disabled = true;
  } else {
    badge.textContent = t("updates.system_count", {count: packages.length});
    badge.classList.add("ok");
    const shown = packages.slice(0, 30);
    list.innerHTML = shown.map(p => `
      <div class="update-package">
        <span class="pkg-name">${escape(p.name)}</span>
        <span class="pkg-version">${escape(p.current_version || "?")} -> ${escape(p.candidate_version || "?")}</span>
      </div>
    `).join("") + (packages.length > shown.length
      ? `<p class="muted">${t("updates.system_more", {count: packages.length - shown.length})}</p>`
      : "");
    install.disabled = false;
  }

  if (d.reboot_required) {
    msg.textContent = t("updates.reboot_required");
  }
}

async function loadSystemUpdateStatus() {
  try {
    const d = await fetch("/api/maintenance/system-updates/status").then(r => r.json());
    renderSystemUpdates(d);
  } catch (e) {}
}

async function scanSystemUpdates(opts={}) {
  const btn = document.getElementById("system-updates-scan");
  const msg = document.getElementById("system-updates-msg");
  if (btn.disabled) return;
  btn.disabled = true;
  msg.classList.remove("error");
  msg.textContent = t("updates.system_scanning");
  renderSystemUpdates({running: true, mode: "scan", packages: []});
  try {
    const r = await fetch("/api/maintenance/system-updates/check", {method: "POST"});
    const j = await r.json();
    renderSystemUpdates(j);
    if (j.ok) {
      msg.textContent = j.count
        ? t("updates.system_found", {count: j.count})
        : t("updates.system_no_updates");
    } else {
      msg.classList.add("error");
      msg.textContent = t("updates.system_scan_failed") + " " +
        (translateBackendMessage(j.error) || j.error || "?");
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
  } finally {
    btn.disabled = false;
    if (!opts.auto) {
      setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 12000);
    }
  }
}

async function pollSystemUpdates() {
  const d = await fetch("/api/maintenance/system-updates/status").then(r => r.json());
  renderSystemUpdates(d);
  if (d.running) {
    setTimeout(pollSystemUpdates, 4000);
  } else {
    const msg = document.getElementById("system-updates-msg");
    msg.classList.toggle("error", d.ok === false);
    msg.textContent = d.ok === false
      ? t("updates.system_install_failed") + " " + (translateBackendMessage(d.error) || d.error || "?")
      : t("updates.system_install_done");
  }
}

document.getElementById("system-updates-scan")
  .addEventListener("click", () => scanSystemUpdates());

document.getElementById("system-updates-install").addEventListener("click", async () => {
  if (!confirm(t("updates.confirm_install_system"))) return;
  const btn = document.getElementById("system-updates-install");
  const msg = document.getElementById("system-updates-msg");
  btn.disabled = true;
  msg.classList.remove("error");
  msg.textContent = t("updates.system_installing");
  try {
    const r = await fetch("/api/maintenance/system-updates/install", {method: "POST"});
    const j = await r.json();
    renderSystemUpdates(j);
    if (j.ok) {
      setTimeout(pollSystemUpdates, 1500);
    } else {
      msg.classList.add("error");
      msg.textContent = t("updates.system_install_failed") + " " +
        (translateBackendMessage(j.error) || j.error || "?");
      btn.disabled = false;
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
    btn.disabled = false;
  }
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
    const logLang = encodeURIComponent(window.I18N.lang || "en");
    const log = await fetch("/api/logs?lang=" + logLang).then(r=>r.text());
    const l = document.getElementById("log");
    l.textContent = log || t("system.log_empty");
    l.scrollTop = l.scrollHeight;
  } catch(e) {}
}

// ---------- Display diagnosis ----------
function renderDiagnosticAssignments(assignments) {
  const el = document.getElementById("diagnostics-assignments");
  if (!assignments || !assignments.length) {
    el.innerHTML = `<p class="muted">${t("common.none")}</p>`;
    return;
  }
  const rows = assignments.map(a => {
    const configured = a.configured_output || t("screens.auto");
    return `
    <tr>
      <td>${escape(a.screen || "-")}</td>
      <td><code>${escape(configured)}</code></td>
      <td>${a.assigned_output ? `<code>${escape(a.assigned_output)}</code>` : t("diag.unassigned")}</td>
      <td>${a.running ? t("common.yes") : t("common.no")}</td>
    </tr>`;
  }).join("");
  el.innerHTML = `
    <h3>${t("diag.assignments")}</h3>
    <table>
      <thead><tr>
        <th>${t("diag.page")}</th>
        <th>${t("diag.configured")}</th>
        <th>${t("diag.assigned")}</th>
        <th>${t("diag.running")}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function loadDiagnostics() {
  const btn = document.getElementById("diagnostics-refresh");
  btn.disabled = true;
  try {
    const data = await fetch("/api/diagnostics").then(r => r.json());
    document.getElementById("diagnostics-time").textContent = data.captured_at || "-";
    renderDiagnosticAssignments(data.assignments || []);
    document.getElementById("diagnostics-xrandr").textContent = data.xrandr || t("system.log_empty");
    document.getElementById("diagnostics-chromium").textContent = data.chromium || t("system.log_empty");
    const log = document.getElementById("diagnostics-log");
    log.textContent = data.log || t("system.log_empty");
    log.scrollTop = log.scrollHeight;
  } catch (e) {
    document.getElementById("diagnostics-assignments").textContent =
      t("common.error") + ": " + e;
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("diagnostics-refresh").addEventListener("click", loadDiagnostics);

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
    msg.textContent = r.message || translateBackendMessage(r.error) || (r.ok ? t("common.saved") : t("common.error"));
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
        msg.textContent = t("common.error") + ": " + (r.message || translateBackendMessage(r.error) || "?");
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
    const warnText = serviceWarnText(it);
    const noteText = serviceNoteText(it);

    // Status-Klasse bestimmen
    let cls = "idle";
    let stateText = t("svc.idle");

    if (!it.installed) {
      cls = "bad";
      stateText = t("svc.missing");
    } else if (warnText) {
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
        ${warnText
          ? `<div class="svc-warn">${escape(warnText)}</div>`
          : (noteText
              ? `<div class="svc-note">${escape(noteText)}</div>`
              : "")}
      </div>
      <span class="svc-state">${stateText}</span>
    `;
    host.appendChild(row);
  });
}

function serviceNoteText(it) {
  return tMaybe("svc.note." + it.key) || it.note || "";
}

function serviceWarnText(it) {
  if (!it.warn) return "";
  if (it.installed === false) {
    return t("svc.warn.missing", {target: it.target || ""});
  }
  if (it.key === "unclutter") {
    return tMaybe("svc.warn.unclutter_wayland") || it.warn;
  }
  return it.warn;
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

function translateBackendReason(reason) {
  const map = {
    "iw nicht installiert": "power.reason.iw_missing",
    "xset nicht installiert": "power.reason.xset_missing",
    "nmcli nicht installiert": "power.reason.nmcli_missing",
    "kein WLAN-Interface": "power.reason.no_wifi_iface",
    "Keine aktive WLAN-Verbindung gefunden": "power.reason.no_active_wifi",
  };
  return map[reason] ? t(map[reason]) : (reason || "");
}

function translateBackendMessage(message) {
  const map = {
    "Keine VERSION-Datei auf origin/main gefunden.": "maint.error.no_version_file",
    "git ist nicht installiert.": "maint.error.git_missing",
    "Dieses Verzeichnis ist kein Git-Repository.": "maint.error.no_git_repo",
    "Ein Update oder Scan laeuft bereits.": "maint.error.scan_busy",
    "Ein Update laeuft bereits.": "maint.error.update_busy",
    "Git-Kommando hat zu lange gedauert.": "maint.error.git_timeout",
    "Git-Update hat zu lange gedauert.": "maint.error.update_timeout",
    "A Raspberry update scan or install is already running.": "updates.error.busy",
    "apt-get is not installed.": "updates.error.apt_missing",
    "Ungültige Config": "settings.error.invalid_config",
    "Ungültige JSON-Daten": "settings.error.invalid_json",
    "Wenn der Zugangsschutz aktiv ist, müssen Benutzername und Passwort gesetzt sein.": "settings.error.auth_required_fields",
    "SSID fehlt": "wifi.error.ssid_missing",
    "name fehlt": "wifi.error.name_missing",
  };
  return map[message] ? t(map[message]) : (translateBackendReason(message) || message || "");
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
      : escape(translateBackendReason(wp.reason) || "-");
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
      state = translateBackendReason(sb.reason) || t("svc.missing");
    } else if (sb.blanking_off) {
      cls = "ok"; state = t("power.state_ok");
    } else {
      cls = "warn"; state = t("power.state_warn");
    }
    const note = sb.available
      ? `${t("power.screensaver")}: <b>${sb.screensaver_timeout === 0 ? t("power.off") : (sb.screensaver_timeout + "s")}</b> &middot; DPMS: <b>${sb.dpms_enabled ? t("power.on") : t("power.off")}</b>`
      : escape(translateBackendReason(sb.reason) || "-");
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
        .map(s => `${s.step}: ${translateBackendReason(s.msg) || s.msg}`).join(" | ");
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
setInterval(loadMaintenanceStatus, 30000);
load();
loadAuthStatus();
loadServices();
loadPower();
loadMaintenanceStatus();

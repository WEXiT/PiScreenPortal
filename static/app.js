let cfg = null;
let monitors = [];
let lastProcs = {};
let lastKiosk = {};
let dirty = false;

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

async function postJson(url, body) {
  const init = {method: "POST", headers: {"Content-Type": "application/json"}};
  if (body !== undefined) init.body = JSON.stringify(body);
  const r = await fetch(url, init);
  let data = {};
  try { data = await r.json(); } catch (e) {}
  if (!r.ok && data.ok === undefined) data.ok = false;
  return data;
}

// ---------- Toasts ----------
function toast(text, type = "info", ms = 4500) {
  const host = document.getElementById("toasts");
  if (!host || !text) return;
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = text;
  host.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 250);
  }, ms);
}

function setBusy(btn, busy) {
  if (!btn) return;
  btn.disabled = busy;
  btn.classList.toggle("busy", busy);
}

// ---------- Unsaved changes ----------
function setDirty(value) {
  dirty = value;
  document.getElementById("dirty-hint").hidden = !value;
}

window.addEventListener("beforeunload", e => {
  if (!dirty) return;
  e.preventDefault();
  e.returnValue = "";
});

// ---------- Tabs ----------
function activateTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  const panel = document.getElementById("tab-" + name);
  if (!tab || !panel) return;

  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(x => x.classList.remove("active"));
  tab.classList.add("active");
  panel.classList.add("active");
  try { sessionStorage.setItem("pisp_tab", name); } catch (e) {}

  if (name === "wifi") loadWifi();
  if (name === "presentation") loadPresentation();
  if (name === "diagnostics") loadDiagnostics();
  if (name === "settings") onSettingsOpen();
  if (name === "system") refreshLogs();
  if (name === "screens") renderLayoutMap();
}

function activeTab() {
  const tab = document.querySelector(".tab.active");
  return tab ? tab.dataset.tab : "dashboard";
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

const brandHome = document.getElementById("brand-home");
if (brandHome) brandHome.addEventListener("click", () => activateTab("dashboard"));

// Re-render on language change
document.addEventListener("i18n-applied", () => {
  if (cfg) { renderMonitors(); renderScreens(); renderPresNameHints(); }
  renderStatusPills();
  refreshStatus();
  loadServices();
  loadPower();
  loadMaintenanceStatus();
  loadSystemUpdateStatus();
  if (activeTab() === "diagnostics") loadDiagnostics();
  if (activeTab() === "settings") loadKeyringStatus();
});

// ---------- Laden ----------
async function load() {
  const [c, m] = await Promise.all([
    fetch("/api/config").then(r => r.json()),
    fetch("/api/monitors").then(r => r.json()),
  ]);
  cfg = c;
  monitors = Array.isArray(m) ? m : [];
  renderMonitors();
  renderScreens();
  renderSettings();
  renderPresNameHints();
  setDirty(false);
  refreshStatus();
}

// ---------- Monitor-Tabelle ----------
function renderMonitors() {
  const tb = document.querySelector("#monitors tbody");
  tb.innerHTML = "";
  if (!monitors.length) {
    tb.innerHTML = `<tr><td colspan="5" class="muted">${t("screens.none_detected")}</td></tr>`;
    return;
  }
  for (const m of monitors) {
    const tr = document.createElement("tr");
    const rot = m.rotation && m.rotation !== "normal" ? ` &middot; ${escape(rotationLabel(m.rotation))}` : "";
    tr.innerHTML = `<td><code>${escape(m.name)}</code></td><td>${m.primary ? t("common.yes") : ""}</td>
      <td>${m.width} &times; ${m.height}${m.rate ? ` @ ${Math.round(m.rate)} Hz` : ""}${rot}</td><td>${m.x}, ${m.y}</td>
      <td>${m.active ? t("screens.live") : t("screens.connected_waiting")}</td>`;
    tb.appendChild(tr);
  }
}

function updateLiveMonitors(nextMonitors) {
  const next = Array.isArray(nextMonitors) ? nextMonitors : [];
  const signature = list => JSON.stringify(list.map(m => [
    m.name, !!m.active, m.x, m.y, m.width, m.height, m.geometry || "", m.rotation || ""
  ]));
  if (signature(next) === signature(monitors)) return;
  monitors = next;
  renderMonitors();
  if (!cfg) return;
  document.querySelectorAll("#screens .screen-card").forEach(card => {
    const i = Number(card.dataset.index);
    const s = cfg.screens[i];
    if (!s) return;
    const out = card.querySelector("select[data-k='output']");
    const res = card.querySelector("select[data-k='resolution']");
    if (out) { out.innerHTML = outputOptions(s.output); out.value = s.output || ""; }
    if (res) { res.innerHTML = resolutionOptions(s, i); res.value = s.resolution || ""; }
  });
  renderLayoutMap();
}

function sortedMonitors(list) {
  return [...list].sort((a, b) =>
    (b.active - a.active) || (a.x - b.x) || (a.y - b.y) || a.name.localeCompare(b.name));
}

function outputOptions(selected) {
  const opts = [`<option value="">${t("screens.auto")}</option>`]
    .concat(sortedMonitors(monitors).map((m, n) =>
      `<option value="${escape(m.name)}" ${m.name === selected ? "selected" : ""}>${n + 1} &middot; ${escape(m.name)} (${m.width}x${m.height})</option>`));
  if (selected && !monitors.some(m => m.name === selected)) {
    opts.push(`<option value="${escape(selected)}" selected>${escape(selected)} (${t("screens.not_detected")})</option>`);
  }
  return opts.join("");
}

function monitorForScreen(s, i) {
  const proc = lastProcs[String(i)];
  const name = s.output || (proc && proc.output) || "";
  return monitors.find(m => m.name === name) || null;
}

function resolutionOptions(s, i) {
  const mon = monitorForScreen(s, i);
  const seen = new Set();
  const modes = [];
  ((mon && mon.available_modes) || []).forEach(mode => {
    if (mode && mode.name && !seen.has(mode.name)) { seen.add(mode.name); modes.push(mode.name); }
  });
  const preferred = mon && mon.preferred_mode;
  const opts = [`<option value="">${t("screens.res_auto")}${preferred ? " (" + escape(preferred) + ")" : ""}</option>`]
    .concat(modes.map(name => `<option value="${escape(name)}" ${name === s.resolution ? "selected" : ""}>${escape(name)}</option>`));
  if (s.resolution && !seen.has(s.resolution)) {
    opts.push(`<option value="${escape(s.resolution)}" selected>${escape(s.resolution)} (${t("screens.not_detected")})</option>`);
  }
  return opts.join("");
}

function rotationLabel(r) {
  return tMaybe("screens.rot_" + r) || r;
}

// ---------- Bildschirme ----------
function duplicateOutputs() {
  const counts = {};
  (cfg.screens || []).forEach(s => {
    if (s.enabled && s.output) counts[s.output] = (counts[s.output] || 0) + 1;
  });
  return new Set(Object.keys(counts).filter(k => counts[k] > 1));
}

function screenStatus(i) {
  const s = cfg && cfg.screens[i];
  const p = lastProcs[String(i)];
  if (!s || !s.enabled) return {cls: "", text: t("screens.status_disabled")};
  if (lastKiosk.presentation_running) return {cls: "warn", text: t("screens.status_presentation")};
  if (!p || !p.running) return {cls: "warn", text: t("screen.inactive")};
  const output = p.output || s.output || "";
  if (p.window_visible === true) return {cls: "ok", text: t("screens.status_live", {output})};
  if (p.window_visible === false) return {cls: "bad", text: t("screens.status_hidden", {output})};
  return {cls: "ok", text: t("screens.status_running", {output})};
}

function renderScreens() {
  const host = document.getElementById("screens");
  host.innerHTML = "";
  const dupes = duplicateOutputs();
  if (!cfg.screens.length) {
    host.innerHTML = `<p class="muted">${t("screens.empty")}</p>`;
  }
  cfg.screens.forEach((s, i) => {
    const card = document.createElement("div");
    const dupe = s.enabled && s.output && dupes.has(s.output);
    const missing = s.enabled && s.output && monitors.length && !monitors.some(m => m.name === s.output);
    card.className = "screen-card" + (s.enabled ? "" : " disabled") + (dupe ? " has-error" : "");
    card.dataset.index = String(i);
    const st = screenStatus(i);
    card.innerHTML = `
      <div class="screen-head">
        <span class="screen-num">${i + 1}</span>
        <input type="text" class="name-input" data-k="name" value="${escape(s.name || "")}"
               placeholder="${escape(t("screens.label_name"))}" aria-label="${escape(t("screens.label_name"))}" maxlength="80">
        <span class="screen-badge ${st.cls}" data-status="${i}">${escape(st.text)}</span>
        <label class="switch"><input type="checkbox" data-k="enabled" ${s.enabled ? "checked" : ""}><span class="track"></span><span>${t("screens.enabled")}</span></label>
        <div class="screen-actions">
          <button type="button" class="btn btn-sm ghost" data-screen-act="restart" title="${escape(t("screens.restart_one_hint"))}">${t("screens.restart_one")}</button>
          <button type="button" class="btn btn-sm ghost danger" data-screen-act="remove">${t("common.remove")}</button>
        </div>
      </div>
      <div class="screen-body">
        <label class="span-4">${t("screens.url")}
          <input type="url" data-k="url" value="${escape(s.url || "")}" placeholder="https://example.com" spellcheck="false">
        </label>
        <label class="span-2">${t("screens.output")}
          <select data-k="output" class="${dupe || missing ? "invalid" : ""}">${outputOptions(s.output)}</select>
        </label>
        <label>${t("screens.resolution")}
          <select data-k="resolution">${resolutionOptions(s, i)}</select>
        </label>
        <label>${t("screens.rotation")}
          <select data-k="rotation">
            ${["normal", "left", "right", "inverted"].map(r => `<option value="${r}" ${r === (s.rotation || "normal") ? "selected" : ""}>${escape(rotationLabel(r))}</option>`).join("")}
          </select>
        </label>
        ${dupe ? `<p class="field-error span-4">${escape(t("screens.dupe_output", {output: s.output}))}</p>` : ""}
        ${missing ? `<p class="field-error span-4">${escape(t("screens.output_missing", {output: s.output}))}</p>` : ""}
        <label>${t("screens.zoom")} <input type="number" step="0.05" min="0.25" max="5" data-k="zoom" value="${s.zoom || 1}"></label>
        <label>${t("screens.reload_interval")} <input type="number" min="0" step="1" data-k="reload_interval" value="${s.reload_interval || 0}"></label>
        <label class="check span-2"><input type="checkbox" data-k="hide_cursor" ${s.hide_cursor ? "checked" : ""}> ${t("screens.hide_cursor")}</label>
      </div>
    `;
    card.querySelectorAll("[data-k]").forEach(el => {
      const evt = (el.tagName === "SELECT" || el.type === "checkbox") ? "change" : "input";
      el.addEventListener(evt, () => {
        const k = el.dataset.k;
        let v;
        if (el.type === "checkbox") v = el.checked;
        else if (el.type === "number") v = el.value === "" ? null : Number(el.value);
        else v = el.value;
        cfg.screens[i][k] = v;
        setDirty(true);
        if (k === "output" || k === "enabled") {
          renderScreens();
        } else if (k === "name" || k === "url") {
          renderLayoutMap();
        }
      });
    });
    card.querySelector("[data-screen-act='remove']").addEventListener("click", () => {
      if (confirm(t("screens.confirm_remove"))) {
        cfg.screens.splice(i, 1);
        setDirty(true);
        renderScreens();
      }
    });
    card.querySelector("[data-screen-act='restart']").addEventListener("click", async ev => {
      if (dirty) { toast(t("screens.save_first"), "warn"); return; }
      const btn = ev.currentTarget;
      setBusy(btn, true);
      try {
        const r = await postJson(`/api/screen/${i}/restart`);
        if (r.ok) toast(t("screens.restarted_one", {name: s.name || i + 1}), "ok");
        else toast(t("common.error") + ": " + (translateBackendMessage(r.error) || "?"), "error");
      } catch (e) {
        toast(t("common.error") + ": " + e, "error");
      } finally {
        setBusy(btn, false);
        setTimeout(refreshStatus, 600);
      }
    });
    host.appendChild(card);
  });
  renderLayoutMap();
}

function updateScreenBadges() {
  if (!cfg) return;
  document.querySelectorAll("[data-status]").forEach(el => {
    const st = screenStatus(Number(el.dataset.status));
    el.className = "screen-badge " + st.cls;
    el.textContent = st.text;
  });
}

// ---------- Monitor layout map ----------
function effectiveOutput(s, i) {
  // Die (evtl. noch ungespeicherte) Konfiguration hat Vorrang, damit Tauschen
  // und Zuordnen sofort auf der Karte sichtbar sind. Automatische Seiten
  // zeigen den Ausgang, auf dem sie gerade laufen.
  const p = lastProcs[String(i)];
  return s.output || (p && p.running && p.output) || "";
}

function renderLayoutMap() {
  const host = document.getElementById("layout-map");
  const hint = document.getElementById("layout-hint");
  const swap = document.getElementById("layout-swap");
  if (!host || !cfg) return;
  const enabled = cfg.screens.map((s, i) => ({s, i})).filter(x => x.s.enabled);
  swap.hidden = enabled.length !== 2;

  const list = sortedMonitors(monitors);
  const messages = [];
  const dupes = duplicateOutputs();
  dupes.forEach(o => messages.push(t("screens.dupe_output", {output: o})));
  enabled.forEach(({s}) => {
    if (s.output && list.length && !list.some(m => m.name === s.output)) {
      messages.push(t("screens.output_missing", {output: s.output}));
    }
  });
  const active = list.filter(m => m.active);
  if (active.length && enabled.length > active.length) {
    messages.push(t("layout.more_screens", {screens: enabled.length, monitors: active.length}));
  }

  if (!list.length) {
    host.innerHTML = `<div class="layout-empty">${t("layout.none")}</div>`;
  } else {
    const boxes = [];
    let maxRight = 0;
    list.filter(m => m.active && m.width > 0).forEach(m => {
      boxes.push({m, x: m.x, y: m.y, w: m.width, h: m.height});
      maxRight = Math.max(maxRight, m.x + m.width);
    });
    list.filter(m => !m.active || !(m.width > 0)).forEach(m => {
      const w = m.width || 1920, h = m.height || 1080;
      boxes.push({m, x: maxRight + 200, y: 0, w, h, idle: true});
      maxRight += 200 + w;
    });
    const minX = Math.min(...boxes.map(b => b.x));
    const minY = Math.min(...boxes.map(b => b.y));
    const totalW = Math.max(...boxes.map(b => b.x + b.w)) - minX;
    const totalH = Math.max(...boxes.map(b => b.y + b.h)) - minY;
    const availW = Math.max(200, host.clientWidth - 36);
    const scaleX = Math.min(availW / totalW, 230 / totalH);
    // Auf schmalen Displays (Handy) werden die Boxen sonst zu flach fuer
    // Seitenname und Status. Getrennte Achsen-Skalierung erhaelt dabei die
    // Anordnung und verhindert Ueberlappungen.
    const minBoxH = Math.min(...boxes.map(b => b.h));
    const scaleY = Math.max(scaleX, 118 / minBoxH);
    const gap = 6;

    const canvas = document.createElement("div");
    canvas.className = "layout-canvas";
    canvas.style.width = Math.round(totalW * scaleX) + "px";
    canvas.style.height = Math.round(totalH * scaleY) + "px";

    boxes.forEach((b, n) => {
      const pages = cfg.screens
        .map((s, i) => ({s, i}))
        .filter(x => x.s.enabled && effectiveOutput(x.s, x.i) === b.m.name);
      let cls = "idle";
      let state = t("layout.no_page");
      if (b.idle) {
        state = t("screens.connected_waiting");
      } else if (pages.length) {
        const st = screenStatus(pages[0].i);
        cls = st.cls || "warn";
        state = st.text;
      }
      const el = document.createElement("div");
      const w = Math.max(40, b.w * scaleX - gap);
      const h = Math.max(40, b.h * scaleY - gap);
      el.className = `mon ${cls}` + (w < 170 || h < 130 ? " compact" : "") + (b.idle ? " idle" : "");
      el.style.left = Math.round((b.x - minX) * scaleX + gap / 2) + "px";
      el.style.top = Math.round((b.y - minY) * scaleY + gap / 2) + "px";
      el.style.width = Math.round(w) + "px";
      el.style.height = Math.round(h) + "px";
      const page = pages.length
        ? pages.map(x => `${x.i + 1} &middot; ${escape(x.s.name || t("screens.label") + " " + (x.i + 1))}`).join("<br>")
        : `<span class="muted">${t("layout.no_page")}</span>`;
      const url = pages.length ? escape(pages[0].s.url || "") : "";
      el.innerHTML = `
        <div class="mon-head"><span class="mon-num">${n + 1}</span><span class="mon-name">${escape(b.m.name)}</span></div>
        <div class="mon-page">${page}</div>
        ${url ? `<div class="mon-url">${url}</div>` : ""}
        <div class="mon-res">${b.m.width || "?"} &times; ${b.m.height || "?"}${b.m.primary ? " &middot; " + t("screens.col_primary") : ""}</div>
        <div class="mon-state">${escape(state)}</div>`;
      el.title = `${b.m.name} – ${state}`;
      canvas.appendChild(el);
    });
    host.innerHTML = "";
    host.appendChild(canvas);
  }

  hint.classList.toggle("warn", messages.length > 0);
  hint.textContent = messages.length ? messages.join(" · ") : t("layout.ok_hint");
}

window.addEventListener("resize", () => {
  clearTimeout(window.__layoutTimer);
  window.__layoutTimer = setTimeout(renderLayoutMap, 150);
});

document.getElementById("layout-identify").addEventListener("click", async ev => {
  const btn = ev.currentTarget;
  setBusy(btn, true);
  try {
    const r = await postJson("/api/monitors/identify");
    if (r.ok) toast(t("layout.identify_running", {count: (r.monitors || []).length}), "ok", 7000);
    else toast(t("common.error") + ": " + (translateBackendMessage(r.error) || "?"), "error");
  } catch (e) {
    toast(t("common.error") + ": " + e, "error");
  } finally {
    setTimeout(() => setBusy(btn, false), 2500);
  }
});

document.getElementById("layout-auto").addEventListener("click", () => {
  const active = sortedMonitors(monitors).filter(m => m.active);
  if (!active.length) { toast(t("layout.none"), "warn"); return; }
  let n = 0;
  cfg.screens.forEach(s => {
    if (!s.enabled) return;
    s.output = n < active.length ? active[n].name : "";
    n += 1;
  });
  setDirty(true);
  renderScreens();
  toast(t("layout.auto_done"), "ok");
});

document.getElementById("layout-swap").addEventListener("click", () => {
  const enabled = cfg.screens.map((s, i) => ({s, i})).filter(x => x.s.enabled);
  if (enabled.length !== 2) return;
  const [a, b] = enabled;
  const outA = effectiveOutput(a.s, a.i);
  const outB = effectiveOutput(b.s, b.i);
  a.s.output = outB;
  b.s.output = outA;
  setDirty(true);
  renderScreens();
  toast(t("layout.swap_done"), "ok");
});

document.getElementById("layout-refresh").addEventListener("click", async ev => {
  const btn = ev.currentTarget;
  setBusy(btn, true);
  try {
    const m = await fetch("/api/monitors?refresh=1").then(r => r.json());
    updateLiveMonitors(m);
    renderLayoutMap();
  } finally {
    setBusy(btn, false);
  }
});

function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
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
  document.getElementById("disable_keyring").checked = cfg.disable_keyring !== false;
  document.getElementById("port").value = cfg.port || 2411;
  document.getElementById("chromium_flags").value = (cfg.chromium_flags || []).join("\n");
  const ar = cfg.auto_reboot || {};
  document.getElementById("auto_reboot_enabled").checked = !!ar.enabled;
  document.getElementById("auto_reboot_mode").value = ar.mode || "daily";
  document.getElementById("auto_reboot_interval").value = ar.interval_minutes || 1440;
  document.getElementById("auto_reboot_time").value = ar.time || "06:00";
  updateAutoRebootFields();
  const a = cfg.auth || {};
  document.getElementById("auth_enabled").checked = !!a.enabled;
  document.getElementById("auth_username").value = a.username || "admin";
  const pw = document.getElementById("auth_password");
  pw.value = "";
  pw.placeholder = a.password_set ? t("settings.password_keep") : t("settings.password_new");
}

function updateAutoRebootFields() {
  const mode = document.getElementById("auto_reboot_mode").value;
  document.getElementById("auto_reboot_interval_wrap").hidden = mode !== "interval";
  document.getElementById("auto_reboot_time_wrap").hidden = mode !== "daily";
}

["auto_reboot_mode", "auto_reboot_enabled"].forEach(id => {
  document.getElementById(id).addEventListener("change", updateAutoRebootFields);
});

document.querySelectorAll("#tab-settings input, #tab-settings select, #tab-settings textarea")
  .forEach(el => {
    if (el.id === "import-file") return;
    el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input",
                        () => setDirty(true));
  });

async function loadKeyringStatus() {
  const el = document.getElementById("keyring-status");
  try {
    const k = await fetch("/api/keyring").then(r => r.json());
    const parts = [
      k.autostart_disabled ? t("keyring.autostart_off") : t("keyring.autostart_on"),
      t("keyring.chromium_basic"),
    ];
    if (k.daemon_running) parts.push(t("keyring.daemon_running"));
    el.textContent = parts.join(" · ");
  } catch (e) {
    el.textContent = "";
  }
}

document.getElementById("add-screen").addEventListener("click", () => {
  cfg.screens.push({
    name: t("screens.new"), enabled: true, url: "https://example.com",
    output: "", resolution: "", rotation: "normal", hide_cursor: true,
    reload_interval: 0, zoom: 1.0,
  });
  setDirty(true);
  renderScreens();
  const cards = document.querySelectorAll("#screens .screen-card");
  const last = cards[cards.length - 1];
  if (last) {
    last.scrollIntoView({behavior: "smooth", block: "center"});
    const url = last.querySelector("[data-k='url']");
    if (url) url.focus();
  }
});

function collectSettings() {
  cfg.auto_start = document.getElementById("auto_start").checked;
  cfg.restart_on_crash = document.getElementById("restart_on_crash").checked;
  cfg.disable_keyring = document.getElementById("disable_keyring").checked;
  cfg.port = parseInt(document.getElementById("port").value, 10) || 2411;
  cfg.chromium_flags = document.getElementById("chromium_flags").value
    .split("\n").map(s => s.trim()).filter(Boolean);
  cfg.auto_reboot = {
    enabled: document.getElementById("auto_reboot_enabled").checked,
    mode: document.getElementById("auto_reboot_mode").value,
    interval_minutes: parseInt(document.getElementById("auto_reboot_interval").value, 10) || 1440,
    time: document.getElementById("auto_reboot_time").value || "06:00",
  };
  const password = document.getElementById("auth_password").value;
  cfg.auth = {
    enabled: document.getElementById("auth_enabled").checked,
    username: document.getElementById("auth_username").value.trim() || "admin",
    password,
    password_set: !!(cfg.auth && cfg.auth.password_set) || !!password,
  };
}

document.getElementById("save").addEventListener("click", async () => {
  const btn = document.getElementById("save");
  const msg = document.getElementById("msg");
  collectSettings();
  const dupes = duplicateOutputs();
  if (dupes.size) {
    const text = t("screens.dupe_output", {output: [...dupes].join(", ")});
    toast(text, "error", 7000);
    activateTab("screens");
    return;
  }
  if (cfg.auth.enabled && !cfg.auth.password_set) {
    toast(t("settings.error.auth_required_fields"), "error", 7000);
    activateTab("settings");
    document.getElementById("auth_password").focus();
    return;
  }
  setBusy(btn, true);
  msg.classList.remove("error");
  msg.textContent = t("common.applying");
  try {
    const r = await postJson("/api/config", cfg);
    if (!r.ok) {
      msg.classList.add("error");
      msg.textContent = "";
      toast(t("common.error") + ": " + (translateBackendMessage(r.error) || "?"), "error", 8000);
      return;
    }
    const applied = await postJson("/api/action/apply");
    await load();
    msg.textContent = "";
    if (applied.ok === false) {
      toast(t("common.error") + ": " + (translateBackendMessage(applied.error) || "?"), "error", 8000);
    } else {
      toast(t("common.saved_applied"), "ok");
    }
    loadAuthStatus();
    loadMaintenanceStatus();
    loadKeyringStatus();
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = "";
    toast(t("common.error") + ": " + e, "error");
  } finally {
    setBusy(btn, false);
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
    setBusy(b, true);
    try {
      const r = await fetch("/api/action/" + act, {method: "POST"});
      if (r.status === 401) { location.href = "/login"; return; }
      if (!r.ok) {
        let err = "?";
        try { const j = await r.json(); err = j.error || err; } catch (e) {}
        toast(t("common.error") + ": " + (translateBackendMessage(err) || err), "error", 8000);
      } else {
        toast(tMaybe("dash.done_" + act.replace("-", "_")) || t("common.done"), "ok", 2500);
      }
    } catch (e) {
      toast(t("common.error") + ": " + e, "error");
    }
    setTimeout(() => { setBusy(b, false); refreshStatus(); }, 800);
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

// ---------- Import / Export ----------
document.getElementById("export-config").addEventListener("click", async () => {
  try {
    const r = await fetch("/api/config/export");
    if (!r.ok) throw new Error("HTTP " + r.status);
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "piscreenportal-config.json";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  } catch (e) {
    toast(t("common.error") + ": " + e, "error");
  }
});

document.getElementById("import-file").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  try {
    const data = JSON.parse(await f.text());
    const r = await postJson("/api/config/import", data);
    if (r.ok) {
      toast(t("settings.import_ok"), "ok");
      setDirty(false);
      setTimeout(() => location.reload(), 900);
    } else {
      toast(t("common.error") + ": " + (translateBackendMessage(r.error) || "?"), "error", 8000);
    }
  } catch (err) {
    toast(t("settings.import_invalid"), "error");
  } finally {
    e.target.value = "";
  }
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
  loadKeyringStatus();
  scanAppUpdates({auto: true});
  loadSystemUpdateStatus();
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

async function scanAppUpdates(opts = {}) {
  const btn = document.getElementById("scan-updates");
  const msg = document.getElementById("updates-msg");
  const status = document.getElementById("update-status");
  if (btn.disabled) return;
  setBusy(btn, true);
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
    setBusy(btn, false);
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
  setBusy(btn, true);
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
    setBusy(btn, false);
    setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 9000);
  }
});

document.getElementById("git-update").addEventListener("click", async () => {
  if (!confirm(t("maint.confirm_update"))) return;
  const btn = document.getElementById("git-update");
  const msg = document.getElementById("updates-msg");
  setBusy(btn, true);
  msg.classList.remove("error");
  msg.textContent = t("maint.update_running");
  try {
    const r = await fetch("/api/maintenance/update", {method: "POST"});
    const j = await r.json();
    if (j.ok) {
      let text = j.changed
        ? t("maint.update_ok_changed")
        : t("maint.update_ok_current");
      if (j.local_changes_stashed) {
        text += " " + t("maint.local_changes_stashed");
      }
      if (j.dependencies === "failed") {
        text += " " + t("maint.deps_failed");
      }
      msg.textContent = text;
      btn.classList.remove("busy");
    } else {
      msg.classList.add("error");
      msg.textContent = t("maint.update_failed") + " " +
        (translateBackendMessage(j.error) || "?");
      setBusy(btn, false);
    }
  } catch (e) {
    msg.classList.add("error");
    msg.textContent = t("common.error") + ": " + e;
    setBusy(btn, false);
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
        <span class="pkg-version">${escape(p.current_version || "?")} &rarr; ${escape(p.candidate_version || "?")}</span>
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
    if (d.running) setTimeout(pollSystemUpdates, 4000);
  } catch (e) {}
}

async function scanSystemUpdates(opts = {}) {
  const btn = document.getElementById("system-updates-scan");
  const msg = document.getElementById("system-updates-msg");
  if (btn.disabled) return;
  setBusy(btn, true);
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
    setBusy(btn, false);
    if (!opts.auto) {
      setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 12000);
    }
  }
}

async function pollSystemUpdates() {
  try {
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
  } catch (e) {
    setTimeout(pollSystemUpdates, 8000);
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
function tile(label, value, cls = "") {
  return `<div class="tile ${cls}"><b>${escape(label)}</b><span>${escape(value ?? "-")}</span></div>`;
}

function renderSysinfo(sys, target, full = false) {
  const el = document.getElementById(target);
  if (!sys) { el.textContent = "-"; return; }
  const mem = sys.memory || {};
  const disk = sys.disk || {};
  let html = tile(t("system.hostname"), sys.hostname)
    + tile(t("system.ip"), sys.ip)
    + tile(t("system.cpu_temp"), sys.cpu_temp, tempClass(sys.cpu_temp))
    + tile(t("system.cpu_load"), sys.cpu_percent || "-")
    + tile(t("system.ram_free"), mem.MemAvailable || "-")
    + tile(t("system.uptime"), sys.uptime || "-");
  if (full) {
    html += tile(t("system.model"), sys.model || "-")
         + tile(t("system.kernel"), sys.kernel || "-")
         + tile(t("system.load_avg"), sys.load_avg || "-")
         + tile(t("system.ram_total"), mem.MemTotal || "-")
         + tile(t("system.swap"), `${mem.SwapFree || "-"} / ${mem.SwapTotal || "-"}`)
         + tile(t("system.disk_free"), `${disk.free || "-"} (${disk.percent || "-"})`)
         + tile(t("system.disk_total"), disk.total || "-")
         + tile(t("system.time"), sys.time || "-");
  }
  el.innerHTML = html;
}

function tempClass(text) {
  const v = parseFloat(String(text || ""));
  if (!isFinite(v)) return "";
  if (v >= 80) return "bad";
  if (v >= 70) return "warn";
  return "";
}

function renderScreenStatus(procs) {
  const el = document.getElementById("screen-status");
  if (!cfg || !cfg.screens.length) { el.innerHTML = `<p class="muted">${t("screens.empty")}</p>`; return; }
  let html = "";
  cfg.screens.forEach((s, i) => {
    const p = procs[String(i)];
    const running = p && p.running;
    const output = (p && p.output) || s.output || t("diag.unassigned");
    let value = s.enabled ? t("screen.inactive") : t("screens.status_disabled");
    let cls = s.enabled ? "warn" : "";
    if (running && p.window_visible === true) {
      value = t("screen.visible", {pid: p.pid, output});
      cls = "ok";
    } else if (running && p.window_visible === false) {
      value = t("screen.not_visible", {pid: p.pid, output});
      cls = "bad";
    } else if (running) {
      value = t("screen.running_unverified", {pid: p.pid, output});
      cls = "ok";
    }
    html += tile(`${i + 1} · ${s.name || t("screens.label") + " " + (i + 1)}`, value, cls);
  });
  el.innerHTML = html;
}

let lastSystem = null;

function renderStatusPills() {
  const kiosk = document.getElementById("pill-kiosk");
  const screens = document.getElementById("pill-screens");
  const temp = document.getElementById("pill-temp");
  const setPill = (el, cls, text) => {
    el.className = "pill " + cls + (el.id === "pill-temp" ? " pill-plain" : "");
    el.querySelector(".pill-text").textContent = text;
  };
  if (lastKiosk.presentation_running) {
    setPill(kiosk, "warn", t("pill.presentation"));
  } else if (lastKiosk.desired_running) {
    setPill(kiosk, "ok", t("pill.kiosk_on"));
  } else {
    setPill(kiosk, "warn", t("pill.kiosk_off"));
  }
  if (cfg) {
    const enabled = cfg.screens.map((s, i) => ({s, i})).filter(x => x.s.enabled);
    const live = enabled.filter(x => {
      const p = lastProcs[String(x.i)];
      return p && p.running && p.window_visible !== false;
    }).length;
    const cls = !enabled.length ? "" : live === enabled.length ? "ok" : live ? "warn" : "bad";
    setPill(screens, cls, t("pill.screens", {live, total: enabled.length}));
  }
  if (lastSystem && lastSystem.cpu_temp && lastSystem.cpu_temp !== "?") {
    setPill(temp, tempClass(lastSystem.cpu_temp), lastSystem.cpu_temp);
    temp.hidden = false;
  } else {
    temp.hidden = true;
  }
}

async function refreshStatus() {
  try {
    const s = await fetch("/api/status").then(r => r.json());
    lastProcs = s.processes || {};
    lastKiosk = s.kiosk || {};
    lastSystem = s.system || null;
    renderSysinfo(s.system, "sysinfo", false);
    renderSysinfo(s.system, "sysinfo-full", true);
    renderScreenStatus(lastProcs);
    updateLiveMonitors(s.monitors || []);
    updateScreenBadges();
    if (activeTab() === "screens") renderLayoutMap();
    renderStatusPills();
    if (s.version) document.getElementById("app-version").textContent = "v" + s.version;
    document.getElementById("status").textContent = JSON.stringify(s.processes, null, 2);
    if (activeTab() === "system") refreshLogs();
  } catch (e) {}
}

async function refreshLogs() {
  try {
    const logLang = encodeURIComponent(window.I18N.lang || "en");
    const log = await fetch("/api/logs?lang=" + logLang).then(r => r.text());
    const l = document.getElementById("log");
    const atBottom = l.scrollHeight - l.scrollTop - l.clientHeight < 40;
    l.textContent = log || t("system.log_empty");
    if (atBottom || !l.dataset.loaded) l.scrollTop = l.scrollHeight;
    l.dataset.loaded = "1";
  } catch (e) {}
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
      <td>${a.window_visible === true ? t("common.yes") :
             a.window_visible === false ? t("common.no") : t("common.unknown")}</td>
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
        <th>${t("diag.visible")}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function loadDiagnostics() {
  const btn = document.getElementById("diagnostics-refresh");
  setBusy(btn, true);
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
    setBusy(btn, false);
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
    const data = await fetch("/api/wifi").then(r => r.json());
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
          <button class="btn btn-sm">${t("common.remove")}</button>
        `;
        div.querySelector("button").addEventListener("click", async () => {
          if (!confirm(t("wifi.confirm_forget") + ' "' + p.name + '"')) return;
          const r = await postJson("/api/wifi/forget", {name: p.name});
          if (!r.ok) toast(t("common.error") + ": " + (r.message || translateBackendMessage(r.error) || "?"), "error");
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
        <button class="btn btn-sm ${n.in_use ? "" : "primary"}">${n.in_use ? t("wifi.reconnect") : t("wifi.connect")}</button>
      `;
      div.querySelector("button").addEventListener("click", () => openWifiModal(n));
      box.appendChild(div);
    });
  } catch (e) {
    box.innerHTML = `<p class="muted">${t("common.error")}: ${escape(e)}</p>`;
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
    const r = await postJson("/api/wifi/add", {ssid, password, hidden, autoconnect});
    msg.textContent = r.message || translateBackendMessage(r.error) || (r.ok ? t("common.saved") : t("common.error"));
    if (r.ok) {
      document.getElementById("wifi-add-ssid").value = "";
      document.getElementById("wifi-add-password").value = "";
      document.getElementById("wifi-add-hidden").checked = false;
      setTimeout(loadWifi, 1500);
    }
  } catch (e) {
    msg.textContent = t("common.error") + ": " + e;
  }
});

document.getElementById("wifi-rescan").addEventListener("click", loadWifi);
document.getElementById("wifi-reset").addEventListener("click", async () => {
  if (!confirm(t("wifi.confirm_reset"))) return;
  const r = await postJson("/api/wifi/reset");
  if (!r.ok) toast(t("common.error") + ": " + (r.message || "?"), "error");
  setTimeout(loadWifi, 3000);
});

// ---------- WiFi Modal ----------
function openWifiModal(n) {
  const modal = document.getElementById("wifi-modal");
  const pwInput = document.getElementById("wifi-password");
  document.getElementById("wifi-modal-ssid").textContent = n.ssid;
  pwInput.value = "";
  document.getElementById("wifi-modal-msg").textContent = "";
  modal.hidden = false;
  const isOpen = !n.security || n.security === "--" || n.security.toLowerCase() === "open"
    || n.security === "offen";
  pwInput.disabled = isOpen;
  if (!isOpen) pwInput.focus();

  const close = () => { modal.hidden = true; document.removeEventListener("keydown", onKey); };
  const onKey = e => {
    if (e.key === "Escape") close();
    if (e.key === "Enter") document.getElementById("wifi-connect").click();
  };
  document.addEventListener("keydown", onKey);
  modal.onclick = e => { if (e.target === modal) close(); };
  document.getElementById("wifi-cancel").onclick = close;
  document.getElementById("wifi-connect").onclick = async () => {
    const pw = pwInput.value;
    const msg = document.getElementById("wifi-modal-msg");
    msg.textContent = t("wifi.connecting");
    try {
      const r = await postJson("/api/wifi/connect", {ssid: n.ssid, password: pw});
      if (r.ok) {
        msg.textContent = t("wifi.connected");
        setTimeout(() => { close(); loadWifi(); }, 1500);
      } else {
        msg.textContent = t("common.error") + ": " + (r.message || translateBackendMessage(r.error) || "?");
      }
    } catch (e) {
      msg.textContent = t("common.error") + ": " + e;
    }
  };
}

// ---------- Präsentation ----------
function renderPresNameHints() {
  const name = (cfg && cfg.presentation && cfg.presentation.airplay_name) || "PiScreenPortal";
  document.querySelectorAll(".pres-name-hint").forEach(el => { el.textContent = name; });
}

function renderPresSettings() {
  const p = (cfg && cfg.presentation) || {};
  document.getElementById("pres-name").value = p.airplay_name || "PiScreenPortal";
  document.getElementById("pres-resolution").value = p.resolution || "1920x1080";
  document.getElementById("pres-stop-kiosk").checked = p.stop_kiosk_while_active !== false;
  renderPresNameHints();
}

async function loadPresentation() {
  renderPresSettings();
  try {
    const s = await fetch("/api/presentation/status").then(r => r.json());
    renderPresStatus(s);
  } catch (e) {}
}

function renderPresStatus(s) {
  const box = document.getElementById("pres-status-box");
  let html = tile(t("pres.installed"), s.available ? t("common.yes") : t("common.no"), s.available ? "ok" : "warn");
  html += tile(t("pres.status"), s.running ? t("pres.status_active") : t("pres.status_stopped"), s.running ? "ok" : "");
  if (s.running && s.started_at) {
    const secs = Math.max(0, Math.floor(Date.now() / 1000 - s.started_at));
    const mins = Math.floor(secs / 60);
    html += tile(t("pres.uptime"), mins > 0 ? `${mins} min ${secs % 60} s` : `${secs} s`);
  }
  box.innerHTML = html;
}

document.getElementById("pres-start").addEventListener("click", async ev => {
  const btn = ev.currentTarget;
  // Einstellungen vorher speichern, damit sie beim Start verwendet werden
  await savePresSettings();
  const msg = document.getElementById("pres-msg");
  msg.textContent = t("pres.starting");
  setBusy(btn, true);
  try {
    const r = await postJson("/api/presentation/start");
    msg.textContent = r.message || (r.ok ? t("common.saved") : t("common.error"));
    if (!r.ok) toast(r.message || t("common.error"), "error", 7000);
    renderPresStatus(r.status || {});
  } finally {
    setBusy(btn, false);
    refreshStatus();
  }
});

document.getElementById("pres-stop").addEventListener("click", async ev => {
  const btn = ev.currentTarget;
  const msg = document.getElementById("pres-msg");
  msg.textContent = t("pres.stopping");
  setBusy(btn, true);
  try {
    const r = await postJson("/api/presentation/stop");
    msg.textContent = t("pres.stopped_running");
    renderPresStatus(r.status || {});
  } finally {
    setBusy(btn, false);
    refreshStatus();
  }
});

async function savePresSettings() {
  // Nur die Praesentations-Einstellungen speichern. Ungespeicherte
  // Bildschirm-Aenderungen duerfen dabei nicht still mitgespeichert werden.
  const presentation = {
    ...((cfg && cfg.presentation) || {}),
    airplay_name: document.getElementById("pres-name").value.trim() || "PiScreenPortal",
    resolution: document.getElementById("pres-resolution").value,
    stop_kiosk_while_active: document.getElementById("pres-stop-kiosk").checked,
  };
  try {
    const fresh = await fetch("/api/config").then(r => r.json());
    fresh.presentation = presentation;
    const r = await postJson("/api/config", fresh);
    if (!r.ok) {
      toast(t("common.error") + ": " + (translateBackendMessage(r.error) || "?"), "error");
      return;
    }
    if (cfg) cfg.presentation = presentation;
    renderPresNameHints();
  } catch (e) {
    toast(t("common.error") + ": " + e, "error");
  }
}

["pres-name", "pres-resolution", "pres-stop-kiosk"].forEach(id => {
  document.getElementById(id).addEventListener("change", savePresSettings);
});

async function refreshPresentation() {
  if (activeTab() !== "presentation") return;
  try {
    const s = await fetch("/api/presentation/status").then(r => r.json());
    renderPresStatus(s);
  } catch (e) {}
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
    "Bildschirm-Konfiguration muss eine Liste sein.": "settings.error.screens_list",
    "Ungültiger Bildschirm-Eintrag.": "settings.error.screen_entry",
    "Wenn der Zugangsschutz aktiv ist, müssen Benutzername und Passwort gesetzt sein.": "settings.error.auth_required_fields",
    "SSID fehlt": "wifi.error.ssid_missing",
    "name fehlt": "wifi.error.name_missing",
    "Kein aktiver Monitor erkannt.": "layout.none",
    "Kein Monitor für diesen Bildschirm gefunden": "screens.error.no_monitor",
    "Unbekannter Bildschirm": "screens.error.unknown",
    "cross_site_request": "common.error.cross_site",
    "Kein Chromium-Fenster gefunden. Läuft der Kiosk und ist xdotool installiert?": "dash.error.no_window",
  };
  if (map[message]) return t(map[message]);
  const duplicate = String(message || "").match(
    /^Monitor-Ausgang (.+) ist mehreren aktiven Bildschirmen zugewiesen\.$/
  );
  if (duplicate) {
    return t("settings.error.duplicate_output", {output: duplicate[1]});
  }
  return translateBackendReason(message) || message || "";
}

function renderPower(d, list, badge) {
  const overall = d.overall || "idle";
  const badgeTxt = overall === "ok"   ? t("power.state_ok") :
                   overall === "warn" ? t("power.state_warn") :
                                        t("svc.idle");
  badge.textContent = badgeTxt;
  badge.className = "svc-state";
  badge.parentElement.classList.remove("power-ok", "power-warn", "power-idle");
  badge.parentElement.classList.add("power-" + overall);

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
      ? `${t("power.iface")} <code>${escape(wp.iface || "?")}</code> &middot; ${t("power.live")}: <b>${escape(wp.state || "?")}</b> &middot; ${t("power.persistent")}: <b>${wp.persistent_disabled ? t("power.off") : t("power.on")}</b>`
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
      <span class="svc-state">${escape(state)}</span>
    `;
    list.appendChild(row);
  }
}

document.getElementById("power-refresh").addEventListener("click", loadPower);

document.getElementById("power-force").addEventListener("click", async () => {
  if (!confirm(t("power.confirm_force"))) return;
  const btn = document.getElementById("power-force");
  const msg = document.getElementById("power-msg");
  setBusy(btn, true);
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
    setBusy(btn, false);
    setTimeout(() => { msg.textContent = ""; msg.classList.remove("error"); }, 8000);
  }
});

// ---------- Init ----------
setInterval(refreshStatus, 5000);
setInterval(refreshPresentation, 5000);
setInterval(loadServices, 15000);
setInterval(loadPower, 30000);
setInterval(loadMaintenanceStatus, 30000);
load().then(() => {
  let tab = null;
  try { tab = sessionStorage.getItem("pisp_tab"); } catch (e) {}
  if (tab && tab !== "dashboard") activateTab(tab);
});
loadAuthStatus();
loadServices();
loadPower();
loadMaintenanceStatus();

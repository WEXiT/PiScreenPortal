// Simple i18n for PiScreenPortal.
// Two locales: en (default) and de.

window.I18N = {
  en: {
    "header.language": "Language",
    "tabs.dashboard": "Dashboard",
    "tabs.screens": "Screens",
    "tabs.presentation": "Presentation",
    "tabs.wifi": "Wi-Fi",
    "tabs.system": "System",
    "tabs.settings": "Settings",

    "common.loading": "Loading...",
    "common.scanning": "Scanning...",
    "common.save": "Save and apply",
    "common.cancel": "Cancel",
    "common.saved": "Saved.",
    "common.applying": "Saved. Applying...",
    "common.saved_restarted": "Saved and kiosk restarted.",
    "common.error": "Error",
    "common.yes": "yes",
    "common.no": "no",
    "common.none": "-",
    "common.remove": "Remove",
    "common.refresh": "Refresh",

    "dash.quick": "Quick actions",
    "dash.start": "Start kiosk",
    "dash.restart": "Restart",
    "dash.stop": "Stop",
    "dash.reload": "Reload page",
    "dash.screen_off": "Monitor off",
    "dash.screen_on": "Monitor on",
    "dash.reboot": "Reboot Raspberry",
    "dash.shutdown": "Shutdown Raspberry",
    "dash.overview": "Overview",
    "dash.screen_status": "Screen status",
    "dash.services": "Services & tools",
    "svc.session": "Session type:",
    "svc.running": "running",
    "svc.stopped": "stopped",
    "svc.installed": "installed",
    "svc.missing": "not installed",
    "svc.idle": "idle",
    "svc.enabled": "enabled at boot",

    "power.title": "Energy & 24/7 mode",
    "power.desc": "For reliable 24/7 kiosk operation, Wi-Fi power saving and screen blanking must be off. Otherwise the Pi drops the AP after a few minutes idle, or the screen turns black.",
    "power.wifi_powersave": "Wi-Fi power saving",
    "power.screen_blanking": "Screen blanking / DPMS",
    "power.screensaver": "screensaver",
    "power.iface": "Interface",
    "power.live": "live",
    "power.persistent": "persistent",
    "power.on": "on",
    "power.off": "off",
    "power.state_ok": "24/7 ready",
    "power.state_warn": "needs attention",
    "power.state_bad": "powersaving active",
    "power.live_only": "live only (not persistent)",
    "power.force": "Force 24/7 mode now",
    "power.applying": "Applying 24/7 settings…",
    "power.applied_ok": "24/7 mode applied. Wi-Fi powersave and screen blanking are off.",
    "power.applied_partial": "Some steps failed:",
    "power.confirm_force": "Disable Wi-Fi power saving and screen blanking now? This is what you want for permanent kiosk operation.",
    "dash.confirm_reboot": "Really reboot the Raspberry?",
    "dash.confirm_shutdown": "Really shut down the Raspberry?",

    "screens.detected": "Detected monitors",
    "screens.col_name": "Name",
    "screens.col_primary": "Primary",
    "screens.col_resolution": "Resolution",
    "screens.col_position": "Position",
    "screens.sorted": "Sorted by X position from left to right.",
    "screens.config": "Screen configuration",
    "screens.add": "Add screen",
    "screens.none_detected": "No monitors detected. Is a graphical session running and is a display connected?",
    "screens.auto": "— automatic —",
    "screens.label": "Screen",
    "screens.label_name": "Label",
    "screens.enabled": "Enabled",
    "screens.output": "Monitor output",
    "screens.url": "URL",
    "screens.rotation": "Rotation",
    "screens.zoom": "Zoom",
    "screens.reload_interval": "Auto-reload (seconds, 0 = off)",
    "screens.hide_cursor": "Hide mouse cursor",
    "screens.confirm_remove": "Really remove this screen?",
    "screens.new": "New screen",

    "pres.title": "Presentation mode (AirPlay)",
    "pres.desc": "Share your iPhone, iPad or Mac screen to the Raspberry via AirPlay. The kiosk is paused during presentation.",
    "pres.start": "Start presentation",
    "pres.stop": "Stop presentation",
    "pres.howto": "How to connect",
    "pres.settings": "Settings",
    "pres.name_label": "AirPlay name (how the Pi appears in the device list)",
    "pres.resolution": "Resolution",
    "pres.pause_kiosk": "Pause kiosk while presenting (recommended)",
    "pres.installed": "UxPlay installed",
    "pres.status": "Status",
    "pres.status_active": "ACTIVE",
    "pres.status_stopped": "Stopped",
    "pres.uptime": "Uptime",
    "pres.starting": "Starting...",
    "pres.stopping": "Stopping...",
    "pres.stopped_running": "Stopped. Kiosk running again.",

    "wifi.current": "Current connection",
    "wifi.rescan": "Rescan networks",
    "wifi.reset": "Restart Wi-Fi",
    "wifi.add_title": "Add Wi-Fi manually",
    "wifi.add_desc": "For hidden networks or networks currently out of range. The profile is saved and will auto-connect when in range.",
    "wifi.password": "Password",
    "wifi.hidden": "SSID is hidden",
    "wifi.autoconnect": "Auto-connect at boot",
    "wifi.save": "Save Wi-Fi",
    "wifi.saved": "Saved Wi-Fi profiles",
    "wifi.available": "Available networks",
    "wifi.connect_to": "Connect to Wi-Fi",
    "wifi.connect": "Connect",
    "wifi.reconnect": "Reconnect",
    "wifi.connected_to": "Connected to",
    "wifi.signal": "Signal strength",
    "wifi.not_connected": "Not connected to any Wi-Fi at the moment.",
    "wifi.no_networks": "No networks found.",
    "wifi.no_saved": "No saved Wi-Fi profiles.",
    "wifi.na": "Wi-Fi management unavailable (nmcli missing).",
    "wifi.security_open": "open",
    "wifi.active": "active",
    "wifi.confirm_forget": "Remove Wi-Fi profile?",
    "wifi.confirm_reset": "Restart Wi-Fi? The connection will briefly drop.",
    "wifi.ssid_missing": "SSID missing.",
    "wifi.connecting": "Connecting...",
    "wifi.connected": "Connected.",

    "system.info": "System information",
    "system.processes": "Running processes",
    "system.hostname": "Hostname",
    "system.ip": "IP address",
    "system.cpu_temp": "CPU temperature",
    "system.cpu_load": "CPU usage",
    "system.ram_free": "RAM free",
    "system.uptime": "Uptime",
    "system.model": "Model",
    "system.kernel": "Kernel",
    "system.load_avg": "Load average",
    "system.ram_total": "RAM total",
    "system.swap": "Swap",
    "system.disk_free": "Disk free",
    "system.disk_total": "Disk total",
    "system.time": "System time",
    "system.log_empty": "(empty)",

    "settings.general": "General",
    "settings.autostart": "Start automatically at boot",
    "settings.crash_restart": "Restart Chromium on crash",
    "settings.port_note": "(service restart required)",
    "settings.flags": "Chromium flags",
    "settings.flags_note": "(one per line)",
    "settings.auth": "Access protection",
    "settings.auth_enable": "Protect web interface with password",
    "settings.username": "Username",
    "settings.password": "Password",
    "settings.auth_note": "When enabled, the web interface shows a login page. The password is stored in plain text in config.json – do not reuse an important one.",
    "auth.signed_in_as": "Signed in as",
    "auth.logout": "Log out",
    "settings.backup": "Backup configuration",
    "settings.export": "Export config",
    "settings.import": "Import config (JSON file)",
    "settings.import_ok": "Import successful. Reloading...",
    "settings.import_invalid": "Not a valid JSON file.",

    "screen.running": "Running (PID {pid})",
    "screen.inactive": "Not running",
  },

  de: {
    "header.language": "Sprache",
    "tabs.dashboard": "Dashboard",
    "tabs.screens": "Bildschirme",
    "tabs.presentation": "Präsentation",
    "tabs.wifi": "WLAN",
    "tabs.system": "System",
    "tabs.settings": "Einstellungen",

    "common.loading": "Lade...",
    "common.scanning": "Suche...",
    "common.save": "Speichern und anwenden",
    "common.cancel": "Abbrechen",
    "common.saved": "Gespeichert.",
    "common.applying": "Gespeichert. Wende an...",
    "common.saved_restarted": "Gespeichert und Kiosk neu gestartet.",
    "common.error": "Fehler",
    "common.yes": "ja",
    "common.no": "nein",
    "common.none": "-",
    "common.remove": "Entfernen",
    "common.refresh": "Aktualisieren",

    "dash.quick": "Schnellzugriff",
    "dash.start": "Kiosk starten",
    "dash.restart": "Neu starten",
    "dash.stop": "Stoppen",
    "dash.reload": "Seite neu laden",
    "dash.screen_off": "Monitor aus",
    "dash.screen_on": "Monitor an",
    "dash.reboot": "Raspberry neu starten",
    "dash.shutdown": "Raspberry ausschalten",
    "dash.overview": "Überblick",
    "dash.screen_status": "Status der Bildschirme",
    "dash.services": "Dienste & Werkzeuge",
    "svc.session": "Sitzungstyp:",
    "svc.running": "läuft",
    "svc.stopped": "gestoppt",
    "svc.installed": "installiert",
    "svc.missing": "nicht installiert",
    "svc.idle": "inaktiv",
    "svc.enabled": "beim Boot aktiv",

    "power.title": "Energie & 24/7-Modus",
    "power.desc": "Für verlässlichen 24/7-Kiosk-Betrieb müssen WLAN-Powersaving und Bildschirmschoner/DPMS aus sein. Sonst trennt der Pi nach wenigen Minuten Idle die WLAN-Verbindung oder schaltet den Monitor schwarz.",
    "power.wifi_powersave": "WLAN-Stromsparmodus",
    "power.screen_blanking": "Bildschirmschoner / DPMS",
    "power.screensaver": "Bildschirmschoner",
    "power.iface": "Interface",
    "power.live": "live",
    "power.persistent": "persistent",
    "power.on": "an",
    "power.off": "aus",
    "power.state_ok": "24/7 bereit",
    "power.state_warn": "prüfen",
    "power.state_bad": "Stromsparen aktiv",
    "power.live_only": "nur live (nicht persistent)",
    "power.force": "24/7-Modus jetzt erzwingen",
    "power.applying": "24/7-Einstellungen werden angewendet…",
    "power.applied_ok": "24/7-Modus aktiviert. WLAN-Powersave und Bildschirmschoner sind aus.",
    "power.applied_partial": "Einige Schritte sind fehlgeschlagen:",
    "power.confirm_force": "WLAN-Stromsparmodus und Bildschirmschoner jetzt deaktivieren? Das ist der richtige Modus für Dauerbetrieb.",
    "dash.confirm_reboot": "Raspberry wirklich neu starten?",
    "dash.confirm_shutdown": "Raspberry wirklich ausschalten?",

    "screens.detected": "Erkannte Monitore",
    "screens.col_name": "Name",
    "screens.col_primary": "Primär",
    "screens.col_resolution": "Auflösung",
    "screens.col_position": "Position",
    "screens.sorted": "Sortiert nach X-Position von links nach rechts.",
    "screens.config": "Bildschirm-Konfiguration",
    "screens.add": "Bildschirm hinzufügen",
    "screens.none_detected": "Keine Monitore erkannt. Läuft eine grafische Sitzung und ist ein Display verbunden?",
    "screens.auto": "— automatisch —",
    "screens.label": "Bildschirm",
    "screens.label_name": "Bezeichnung",
    "screens.enabled": "Aktiviert",
    "screens.output": "Monitor-Ausgang",
    "screens.url": "URL",
    "screens.rotation": "Rotation",
    "screens.zoom": "Zoom",
    "screens.reload_interval": "Auto-Reload (Sekunden, 0 = aus)",
    "screens.hide_cursor": "Mauszeiger verbergen",
    "screens.confirm_remove": "Diesen Bildschirm wirklich entfernen?",
    "screens.new": "Neuer Bildschirm",

    "pres.title": "Präsentationsmodus (AirPlay)",
    "pres.desc": "Teile den Bildschirm von iPhone, iPad oder Mac per AirPlay auf den Raspberry. Während der Präsentation pausiert der Kiosk.",
    "pres.start": "Präsentation starten",
    "pres.stop": "Präsentation beenden",
    "pres.howto": "Anleitung",
    "pres.settings": "Einstellungen",
    "pres.name_label": "AirPlay-Name (so erscheint der Pi in der Geräteliste)",
    "pres.resolution": "Auflösung",
    "pres.pause_kiosk": "Kiosk während Präsentation pausieren (empfohlen)",
    "pres.installed": "UxPlay installiert",
    "pres.status": "Status",
    "pres.status_active": "AKTIV",
    "pres.status_stopped": "Gestoppt",
    "pres.uptime": "Laufzeit",
    "pres.starting": "Starte...",
    "pres.stopping": "Beende...",
    "pres.stopped_running": "Beendet. Kiosk läuft wieder.",

    "wifi.current": "Aktuelle Verbindung",
    "wifi.rescan": "Netzwerke neu suchen",
    "wifi.reset": "WLAN neu starten",
    "wifi.add_title": "WLAN manuell hinzufügen",
    "wifi.add_desc": "Für unsichtbare WLANs oder wenn das Netz gerade nicht in Reichweite ist. Das Profil wird gespeichert und beim nächsten Start automatisch verbunden.",
    "wifi.password": "Passwort",
    "wifi.hidden": "SSID ist unsichtbar",
    "wifi.autoconnect": "Automatisch verbinden beim Booten",
    "wifi.save": "WLAN speichern",
    "wifi.saved": "Gespeicherte WLANs",
    "wifi.available": "Verfügbare Netzwerke",
    "wifi.connect_to": "Mit WLAN verbinden",
    "wifi.connect": "Verbinden",
    "wifi.reconnect": "Erneut verbinden",
    "wifi.connected_to": "Verbunden mit",
    "wifi.signal": "Signalstärke",
    "wifi.not_connected": "Aktuell mit keinem WLAN verbunden.",
    "wifi.no_networks": "Keine Netzwerke gefunden.",
    "wifi.no_saved": "Keine gespeicherten WLANs.",
    "wifi.na": "WLAN-Verwaltung nicht verfügbar (nmcli fehlt).",
    "wifi.security_open": "offen",
    "wifi.active": "aktiv",
    "wifi.confirm_forget": "WLAN-Profil entfernen?",
    "wifi.confirm_reset": "WLAN neu starten? Die Verbindung bricht kurz ab.",
    "wifi.ssid_missing": "SSID fehlt.",
    "wifi.connecting": "Verbinde...",
    "wifi.connected": "Verbunden.",

    "system.info": "System-Informationen",
    "system.processes": "Laufende Prozesse",
    "system.hostname": "Hostname",
    "system.ip": "IP-Adresse",
    "system.cpu_temp": "CPU-Temperatur",
    "system.cpu_load": "CPU-Auslastung",
    "system.ram_free": "RAM frei",
    "system.uptime": "Laufzeit",
    "system.model": "Modell",
    "system.kernel": "Kernel",
    "system.load_avg": "Load Average",
    "system.ram_total": "RAM gesamt",
    "system.swap": "Swap",
    "system.disk_free": "Festplatte frei",
    "system.disk_total": "Festplatte gesamt",
    "system.time": "Systemzeit",
    "system.log_empty": "(leer)",

    "settings.general": "Allgemein",
    "settings.autostart": "Automatisch beim Boot starten",
    "settings.crash_restart": "Chromium bei Absturz neu starten",
    "settings.port_note": "(Dienstneustart nötig)",
    "settings.flags": "Chromium-Flags",
    "settings.flags_note": "(eine pro Zeile)",
    "settings.auth": "Zugangsschutz",
    "settings.auth_enable": "Webinterface mit Passwort schützen",
    "settings.username": "Benutzername",
    "settings.password": "Passwort",
    "settings.auth_note": "Wenn aktiv, zeigt das Webinterface eine Login-Seite. Das Passwort wird im Klartext in config.json gespeichert – bitte kein wichtiges wiederverwenden.",
    "auth.signed_in_as": "Angemeldet als",
    "auth.logout": "Abmelden",
    "settings.backup": "Konfiguration sichern",
    "settings.export": "Config exportieren",
    "settings.import": "Config importieren (JSON-Datei)",
    "settings.import_ok": "Import erfolgreich. Die Seite wird neu geladen...",
    "settings.import_invalid": "Keine gültige JSON-Datei.",

    "screen.running": "Läuft (PID {pid})",
    "screen.inactive": "Nicht aktiv",
  },
};

window.I18N.lang = localStorage.getItem("pisp_lang") || "en";

window.t = function (key, params) {
  const lang = window.I18N.lang;
  let str = (window.I18N[lang] && window.I18N[lang][key])
         || (window.I18N.en && window.I18N.en[key])
         || key;
  if (params) {
    for (const k in params) str = str.replace("{" + k + "}", params[k]);
  }
  return str;
};

function setLabelText(el, text) {
  // Replace ONLY the first text node, keep child elements (input, select, etc.) intact.
  for (const node of el.childNodes) {
    if (node.nodeType === Node.TEXT_NODE) {
      node.textContent = text + " ";
      return;
    }
  }
  el.prepend(document.createTextNode(text + " "));
}

window.applyI18n = function () {
  document.documentElement.lang = window.I18N.lang;
  document.querySelectorAll("[data-i18n]").forEach(el => {
    const key = el.getAttribute("data-i18n");
    const txt = window.t(key);
    // If element has element children (input/select/etc.), keep them and only replace text.
    const hasElementChildren = Array.from(el.childNodes).some(n => n.nodeType === Node.ELEMENT_NODE);
    if (hasElementChildren) {
      setLabelText(el, txt);
    } else {
      el.textContent = txt;
    }
  });
  document.querySelectorAll("[data-i18n-html]").forEach(el => {
    const key = el.getAttribute("data-i18n-html");
    if (window.I18N[window.I18N.lang] && window.I18N[window.I18N.lang][key]) {
      el.innerHTML = window.I18N[window.I18N.lang][key];
    }
  });
  document.dispatchEvent(new CustomEvent("i18n-applied"));
};

document.addEventListener("DOMContentLoaded", () => {
  const sel = document.getElementById("lang-select");
  if (sel) {
    sel.value = window.I18N.lang;
    sel.addEventListener("change", () => {
      window.I18N.lang = sel.value;
      localStorage.setItem("pisp_lang", sel.value);
      window.applyI18n();
    });
  }
  window.applyI18n();
});

// HTML translations for list items with inline markup.
window.I18N.en["pres.howto_ios"] = '<b>iPhone / iPad:</b> open Control Center, tap <i>Screen Mirroring</i>, choose <code id="pres-name-hint">PiScreenPortal</code>.';
window.I18N.en["pres.howto_mac"] = '<b>Mac:</b> Control Center &rarr; Screen Mirroring &rarr; <code>PiScreenPortal</code>.';
window.I18N.en["pres.howto_win"] = '<b>Windows / Android:</b> AirPlay is not natively supported. Recommended: <a href="https://www.deskreen.com" target="_blank">Deskreen</a> or AirMyPC.';

window.I18N.de["pres.howto_ios"] = '<b>iPhone / iPad:</b> Kontrollzentrum öffnen, auf <i>Bildschirmsynchronisierung</i> tippen, <code id="pres-name-hint">PiScreenPortal</code> wählen.';
window.I18N.de["pres.howto_mac"] = '<b>Mac:</b> Kontrollzentrum &rarr; Bildschirmsynchronisierung &rarr; <code>PiScreenPortal</code>.';
window.I18N.de["pres.howto_win"] = '<b>Windows / Android:</b> AirPlay nicht nativ verfügbar. Empfohlen: <a href="https://www.deskreen.com" target="_blank">Deskreen</a> oder AirMyPC.';

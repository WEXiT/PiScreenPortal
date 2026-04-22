# PiScreenPortal – Live Demo

A fully client-side, interactive demo of the PiScreenPortal web UI. No
Raspberry Pi, no Python, no backend required: a small JavaScript shim
(`demo-api.js`) intercepts every `fetch("/api/...")` call and returns
realistic mock data from an in-memory state.

## Run locally

The demo folder is **self-contained** – all assets (CSS / JS / logo) live
inside it, so any static file server works:

```bash
# from inside the demo/ folder
python3 -m http.server 8000
# → http://localhost:8000/
```

or from the repo root:

```bash
python3 -m http.server 8000
# → http://localhost:8000/demo/
```

Opening `index.html` directly via `file://` will **not** work because
browsers block `fetch()` in that mode.

## Host on GitHub Pages

1. Push the repository to GitHub.
2. In the repo: **Settings → Pages → Build from branch**, select `main`
   (or `master`) and folder `/ (root)`.
3. Once deployed, the demo is reachable at:
   ```
   https://<user>.github.io/<repo>/demo/
   ```

The demo uses only relative paths, so it works under any sub-path.

## What is simulated?

| Feature                 | Demo behaviour                                      |
|-------------------------|-----------------------------------------------------|
| Dashboard / sysinfo     | Live values (CPU temp, RAM, uptime) with jitter     |
| Screens                 | 2 monitors, 3 pre-configured kiosk screens          |
| Add / edit / save       | Updates in-memory state, survives until page reload |
| Reboot / shutdown / ... | Logged to console & system log, no real action      |
| Wi-Fi list              | 5 fake networks, connect / forget / add all work    |
| Presentation (AirPlay)  | Start / stop toggles a fake running state           |
| Config export           | Disabled in demo (shows an alert)                   |

## Files

- `index.html` – copy of the main UI with the mock script injected first
- `demo-api.js` – the fake backend (`fetch` interceptor)
- `style.css`, `app.js`, `i18n.js`, `logo.png` – copies of the real assets
  (kept in sync manually; re-copy from `../static/` when the app changes)

## Reset demo state

Reload the page. All state lives in memory only.

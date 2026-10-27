#!/usr/bin/env python3
"""Erzeugt die Offline-Demo in docs/ aus der echten Weboberflaeche.

Nur docs/demo-api.js (die simulierte API) wird von Hand gepflegt. Alles
andere wird aus templates/ und static/ kopiert, damit die Demo nicht hinter
der echten Oberflaeche zurueckbleibt:

    python3 tools/build_demo.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATIC = ROOT / "static"
COPIED_ASSETS = ("app.js", "i18n.js", "style.css", "logo.png", "support.jpg")
BANNER = (
    '<div class="demo-banner">Live demo &middot; simulated data, nothing is '
    'sent to a Raspberry Pi &middot; '
    '<a href="https://github.com/WEXiT/PiScreenPortal">Get PiScreenPortal on '
    'GitHub</a></div>'
)


def build() -> list[Path]:
    DOCS.mkdir(exist_ok=True)
    written = []
    for name in COPIED_ASSETS:
        source, target = STATIC / name, DOCS / name
        if target.exists() and target.read_bytes() == source.read_bytes():
            continue
        shutil.copyfile(source, target)
        written.append(target)

    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/', '"')
    html = html.replace("<!--DEMO_BANNER-->", BANNER)
    html = html.replace(
        '<script src="i18n.js"></script>',
        '<!-- Demo mock API must load BEFORE app.js -->\n'
        '<script src="demo-api.js"></script>\n'
        '<script src="i18n.js"></script>',
    )
    if "demo-api.js" not in html or "/static/" in html:
        raise SystemExit("templates/index.html hat ein unerwartetes Format")
    target = DOCS / "index.html"
    target.write_text(html, encoding="utf-8", newline="\n")
    written.append(target)
    return written


if __name__ == "__main__":
    for path in build():
        print(f"geschrieben: {path.relative_to(ROOT)}")

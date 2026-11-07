#!/usr/bin/env python3
"""DTEK KREM schedule scraper. Runs on a GitHub Actions runner.

Imperva hard-blocks our home ASN, but trusts runner IPs, so the plain
curl_cffi handshake works here: stub page -> cookies -> real page -> CSRF
-> POST /ua/ajax. Output: out/schedule.json (+ out/raw_*.json for debugging).
"""
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from curl_cffi import requests

BASE = "https://www.dtek-krem.com.ua"
PAGE = f"{BASE}/ua/shutdowns"
AJAX = f"{BASE}/ua/ajax"
AL = "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"
XHR_HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": AL,
    "X-Requested-With": "XMLHttpRequest",
    "Origin": BASE,
    "Referer": PAGE,
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)


def is_stub(html: str) -> bool:
    # The Imperva stub is a tiny ~800-1000 byte iframe page. The real
    # shutdowns page is ~1MB and itself references Incapsula resources,
    # so substring checks only make sense on tiny bodies.
    return len(html) < 2500


def load_page(s) -> str:
    """Imperva serves a tiny stub first; the next GET with fresh cookies passes."""
    for delay in (0, 2, 8):
        time.sleep(delay)
        r = s.get(PAGE, headers={"Accept-Language": AL}, timeout=30)
        if r.status_code == 200 and not is_stub(r.text):
            return r.text
        print(f"stub/blocked: status={r.status_code} len={len(r.text)}", flush=True)
    raise SystemExit("page still blocked after retries")


def extract_csrf(html: str):
    m = re.search(r'<meta[^>]*csrf[^>]*content="([^"]+)"', html, re.I)
    return m.group(1) if m else None


def main():
    s = requests.Session(impersonate="chrome")
    html = load_page(s)
    token = extract_csrf(html)
    print(f"page ok: len={len(html)} csrf={'yes' if token else 'NO'}", flush=True)
    (OUT / "raw_page.html").write_text(html, encoding="utf-8")
    if not token:
        raise SystemExit("no csrf token in page")

    headers = dict(XHR_HEADERS, **{"X-Csrf-Token": token})
    results = {}

    # full region schedule: fact + preset in one call
    r = s.post(AJAX, data={"method": "checkDisconUpdate", "update": ""},
               headers=headers, timeout=30)
    print(f"checkDisconUpdate: {r.status_code} len={len(r.text)}", flush=True)
    try:
        results["checkDisconUpdate"] = r.json()
    except ValueError:
        results["checkDisconUpdate"] = {"_raw": r.text[:2000]}

    # sanity probe: city/street catalog (cheap, proves the session works)
    r2 = s.post(AJAX, data={"method": "getStreets"}, headers=headers, timeout=30)
    print(f"getStreets: {r2.status_code} len={len(r2.text)}", flush=True)
    try:
        results["getStreets"] = r2.json()
    except ValueError:
        results["getStreets"] = {"_raw": r2.text[:2000]}

    (OUT / "raw_api.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")

    now = datetime.now()
    schedule = {
        "version": 1,
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "dtek-krem.com.ua",
        "region": "kyivska-oblast",
        "today_date": now.strftime("%Y-%m-%d"),
        "tomorrow_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "groups": extract_groups(results["checkDisconUpdate"], html),
    }
    (OUT / "schedule.json").write_text(
        json.dumps(schedule, ensure_ascii=False, indent=1), encoding="utf-8")
    print("schedule.json written, groups:",
          len(schedule["groups"]) or "not parsed yet (raw saved)", flush=True)


def extract_groups(update_resp, html):
    """Best-effort group schedule. v1: dump known shapes, refine after first run."""
    groups = {}
    data = update_resp if isinstance(update_resp, dict) else {}

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if re.fullmatch(r"\d\.\d", str(k)):
                    groups[str(k)] = v
                else:
                    walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(data)
    if not groups:
        # fallback: pages often embed the preset as JSON in a script tag
        for m in re.finditer(r"\{[^{}]*\"1\.1\"[^{}]*\}", html):
            try:
                frag = json.loads(m.group(0))
                groups.update(frag)
            except ValueError:
                continue
    return groups


if __name__ == "__main__":
    main()

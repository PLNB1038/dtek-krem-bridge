#!/usr/bin/env python3
"""DTEK KREM schedule scraper. Runs on a GitHub Actions runner.

Imperva hard-blocks our home ASN, but trusts runner IPs, so the plain
curl_cffi handshake works here: tiny stub -> cookies -> real page.
The shutdowns page embeds everything as JS globals:

    DisconSchedule.preset = {days, sch_names, time_zone, time_type,
                             data: {GPVx.x: {weekday: {hour: status}}},
                             updateFact}
    DisconSchedule.fact   = {data: {unix_day: {GPVx.x: {hour: status}}},
                             update, today}

Output: out/schedule.json (normalized) + raw_preset.json / raw_fact.json.
"""
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from curl_cffi import requests

BASE = "https://www.dtek-krem.com.ua"
PAGE = f"{BASE}/ua/shutdowns"
AL = "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"
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


def extract_js_blob(html: str, name: str):
    """Pull `DisconSchedule.<name> = {...}` as a JSON string."""
    i = html.find(f"DisconSchedule.{name} =")
    if i < 0:
        return None
    j = html.find("{", i)
    depth = 0
    instr = False
    esc = False
    for k in range(j, len(html)):
        c = html[k]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if instr:
            if c == '"':
                instr = False
            continue
        if c == '"':
            instr = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[j:k + 1]
    return None


def main():
    s = requests.Session(impersonate="chrome")
    html = load_page(s)
    print(f"page ok: len={len(html)}", flush=True)

    blobs = {}
    for name in ("preset", "fact"):
        raw = extract_js_blob(html, name)
        if not raw:
            raise SystemExit(f"DisconSchedule.{name} not found in page")
        blobs[name] = json.loads(raw)
        (OUT / f"raw_{name}.json").write_text(
            json.dumps(blobs[name], ensure_ascii=False, indent=1), encoding="utf-8")

    preset, fact = blobs["preset"], blobs["fact"]
    today_ts = fact.get("today")
    fact_today = (fact.get("data") or {}).get(str(today_ts) if today_ts else "", {})

    groups = {}
    for gkey, week in (preset.get("data") or {}).items():
        g = gkey.removeprefix("GPV")
        groups[g] = {
            "name": (preset.get("sch_names") or {}).get(gkey, g),
            "week": week,  # {weekday(1-7): {hour(1-24): status}}
            "fact_today": fact_today.get(gkey) or {},
        }

    now = datetime.now(ZoneInfo("Europe/Kyiv"))  # з розпізнаваним зміщенням
    schedule = {
        "version": 2,
        "updated_at": now.isoformat(timespec="seconds"),
        "source": "dtek-krem.com.ua",
        "region": "kyivska-oblast",
        "dtek_updated": preset.get("updateFact") or fact.get("update"),
        "today_ts": today_ts,
        "today_date": now.strftime("%Y-%m-%d"),
        "tomorrow_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
        "time_type": preset.get("time_type") or {},
        "time_zone": preset.get("time_zone") or {},
        "groups": groups,
    }
    (OUT / "schedule.json").write_text(
        json.dumps(schedule, ensure_ascii=False, indent=1), encoding="utf-8")

    filled = sum(1 for g in groups.values() if g["fact_today"])
    print(f"schedule.json: {len(groups)} groups, fact today for {filled}, "
          f"dtek_updated={schedule['dtek_updated']}", flush=True)


if __name__ == "__main__":
    main()

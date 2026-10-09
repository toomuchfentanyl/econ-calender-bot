#!/usr/bin/env python3
"""
Economic calendar -> Discord alerts.

Posts high-impact USD events to a Discord channel ~10 minutes before release.
Designed to run on GitHub Actions every 5 minutes. Stdlib only, no dependencies.

Setup:
  1. In Discord: channel settings -> Integrations -> Webhooks -> New Webhook,
     copy the webhook URL.
  2. In this repo: Settings -> Secrets and variables -> Actions -> New secret
     named DISCORD_WEBHOOK_URL, paste the URL. (Never put the URL in the code.)
  3. Push these files. The workflow runs automatically every 5 minutes.

The workflow commits .posted.json back to the repo so an event is never
posted twice, even though each cron run starts fresh.
"""

import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FEED_URL = "https://nfs.farebook.com/ff_calendar_thisweek.xml"  # Forex Factory weekly feed
ET_ZONE = ZoneInfo("America/New_York")
LOOKAHEAD = timedelta(minutes=12)  # alert for events releasing within this window

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".posted.json")

# Set to "@everyone" if you want the whole server pinged on high-impact news.
MENTION = ""


def load_state():
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
            return set(data.get("posted", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_state(posted):
    with open(STATE_PATH, "w") as f:
        json.dump({"posted": sorted(posted)[-500:]}, f, indent=1)


def fetch_events():
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    events = []
    for e in root.findall("event"):
        events.append({
            "title": (e.findtext("title") or "").strip(),
            "country": (e.findtext("country") or "").strip(),
            "date": (e.findtext("date") or "").strip(),      # MM-DD-YYYY
            "time": (e.findtext("time") or "").strip(),      # e.g. 8:30am
            "impact": (e.findtext("impact") or "").strip(),
            "forecast": (e.findtext("forecast") or "").strip(),
            "previous": (e.findtext("previous") or "").strip(),
        })
    return events


def event_time_et(ev):
    """Event datetime in America/New_York, or None if it has no fixed time."""
    t = ev["time"].lower()
    if not t or t in ("all day", "tentative"):
        return None
    try:
        dt = datetime.strptime(f"{ev['date']} {t}", "%m-%d-%Y %I:%M%p")
    except ValueError:
        return None
    return dt.replace(tzinfo=ET_ZONE)


def post_to_discord(webhook_url, ev, when_et):
    embed = {
        "title": f"\U0001f534 USD \u00b7 {ev['title']}",
        "description": (
            f"\u23f0 **{when_et.strftime('%-I:%M %p')} ET** \u2014 releasing in ~10 min\n"
            f"Forecast: {ev['forecast'] or '\u2014'} \u00b7 Prior: {ev['previous'] or '\u2014'}\n\n"
            f"\u26a0\ufe0f No new trades until 5 min after release."
        ),
        "color": 0xE74C3C,
    }
    payload = {"username": "News Calendar", "embeds": [embed]}
    if MENTION:
        payload["content"] = MENTION
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        webhook_url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        if r.status not in (200, 204):
            raise RuntimeError(f"Discord returned HTTP {r.status}")


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set - skipping.")
        return 0
    try:
        events = fetch_events()
    except Exception as exc:  # feed hiccups shouldn't fail the cron loudly
        print(f"Calendar feed unavailable: {exc}")
        return 0

    posted = load_state()
    now = datetime.now(ET_ZONE)
    new_posts = 0
    for ev in events:
        if ev["country"] != "USD" or ev["impact"] != "High":
            continue
        when = event_time_et(ev)
        if when is None:
            continue
        if timedelta(0) <= (when - now) <= LOOKAHEAD:
            eid = f"{ev['date']}|{ev['time']}|{ev['title']}"
            if eid in posted:
                continue
            try:
                post_to_discord(webhook_url, ev, when)
                posted.add(eid)
                new_posts += 1
                print(f"Posted: {ev['title']} at {ev['time']} ET")
            except Exception as exc:
                print(f"Discord post failed for {ev['title']}: {exc}")
    save_state(posted)
    print(f"Done. {new_posts} new alert(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

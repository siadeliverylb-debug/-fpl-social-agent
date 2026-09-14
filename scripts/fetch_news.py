"""Poll the FPL bootstrap-static API and diff against the last-seen snapshot
in state.json to produce a list of "story" dicts worth posting about."""

import json
import os
from datetime import datetime, timezone

import requests

BOOTSTRAP_URL = "https://fantasy.premierleague.com/api/bootstrap-static/"
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")

STATUS_LABELS = {
    "a": "available",
    "d": "doubtful",
    "i": "injured",
    "s": "suspended",
    "u": "unavailable",
    "n": "not in squad",
}


def load_state(path=STATE_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state, path=STATE_PATH):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def fetch_bootstrap():
    resp = requests.get(BOOTSTRAP_URL, timeout=20)
    resp.raise_for_status()
    return resp.json()


def build_snapshot(data):
    teams = {t["id"]: t["short_name"] for t in data["teams"]}
    snapshot = {}
    for p in data["elements"]:
        snapshot[str(p["id"])] = {
            "web_name": p["web_name"],
            "team": teams.get(p["team"], "?"),
            "now_cost": p["now_cost"],
            "status": p["status"],
            "news": p["news"],
            "news_added": p["news_added"],
        }
    return snapshot


def diff_snapshots(old, new):
    stories = []
    if old is None:
        return stories  # first run: establish baseline only, nothing to report

    for pid, cur in new.items():
        prev = old.get(pid)
        if prev is None:
            continue  # player not seen before (rare mid-season addition), skip

        if cur["now_cost"] != prev["now_cost"]:
            delta = cur["now_cost"] - prev["now_cost"]
            stories.append({
                "type": "price_change",
                "key": f"price:{pid}:{cur['now_cost']}",
                "player": cur["web_name"],
                "team": cur["team"],
                "direction": "rise" if delta > 0 else "fall",
                "delta_millions": round(abs(delta) / 10, 1),
                "new_price_millions": round(cur["now_cost"] / 10, 1),
            })

        if cur["news"] and cur["news"] != prev["news"]:
            stories.append({
                "type": "status_change",
                "key": f"status:{pid}:{cur['news_added']}",
                "player": cur["web_name"],
                "team": cur["team"],
                "status": STATUS_LABELS.get(cur["status"], cur["status"]),
                "news": cur["news"],
            })

    return stories


def deadline_stories(data, now=None):
    now = now or datetime.now(timezone.utc)
    stories = []
    for ev in data["events"]:
        if ev["finished"]:
            continue
        deadline = datetime.fromisoformat(ev["deadline_time"].replace("Z", "+00:00"))
        hours_until = (deadline - now).total_seconds() / 3600
        if 0 < hours_until <= 24:
            bucket = "24h" if hours_until > 2 else "2h"
            stories.append({
                "type": "deadline_reminder",
                "key": f"deadline:{ev['id']}:{bucket}",
                "gw": ev["id"],
                "bucket": bucket,
                "hours_until": round(hours_until, 1),
            })
        break  # only the next unfinished event is relevant
    return stories


def recap_stories(data, state):
    stories = []
    recapped = set(state.get("recapped_events", []))
    for ev in data["events"]:
        if ev["finished"] and ev["id"] not in recapped:
            stories.append({
                "type": "gw_recap",
                "key": f"recap:{ev['id']}",
                "gw": ev["id"],
                "most_captained": ev.get("most_captained"),
                "highest_score": ev.get("highest_score"),
                "most_selected": ev.get("most_selected"),
            })
    return stories


def main():
    state = load_state()
    data = fetch_bootstrap()
    new_snapshot = build_snapshot(data)

    stories = []
    stories += diff_snapshots(state.get("last_snapshot"), new_snapshot)
    stories += deadline_stories(data)
    stories += recap_stories(data, state)

    state["last_snapshot"] = new_snapshot
    state["last_snapshot_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    print(json.dumps(stories, indent=2))
    return stories


if __name__ == "__main__":
    main()

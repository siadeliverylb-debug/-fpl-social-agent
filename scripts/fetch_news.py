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


def _classify_status(status_code, news_text):
    """The 'news' field covers far more than injuries -- loans, permanent
    transfers, departures, suspensions -- so pick an honest category instead
    of always framing it as an injury alert."""
    text = news_text.lower()

    if status_code == "s":
        return "suspension"
    if status_code in ("i", "d"):
        return "injury"
    if "loan" in text:
        return "loan"
    if "joined" in text or "permanently" in text or "transfer" in text:
        return "transfer"
    if "departed" in text or "free agent" in text or "released" in text:
        return "departure"
    return "availability"


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

    price_changes = []
    injury_changes = []
    for pid, cur in new.items():
        prev = old.get(pid)
        if prev is None:
            continue  # player not seen before (rare mid-season addition), skip

        if cur["now_cost"] != prev["now_cost"]:
            delta = cur["now_cost"] - prev["now_cost"]
            price_changes.append({
                "pid": pid,
                "player": cur["web_name"],
                "team": cur["team"],
                "direction": "rise" if delta > 0 else "fall",
                "delta_millions": round(abs(delta) / 10, 1),
                "new_price_millions": round(cur["now_cost"] / 10, 1),
            })

        if cur["news"] and cur["news"] != prev["news"]:
            category = _classify_status(cur["status"], cur["news"])
            entry = {
                "pid": pid,
                "player": cur["web_name"],
                "team": cur["team"],
                "status": STATUS_LABELS.get(cur["status"], cur["status"]),
                "news": cur["news"],
                "category": category,
            }
            if category == "injury":
                # Injury news lands in bursts (FPL's editorial team updates
                # several players' statuses in the same pass), so like price
                # changes, injuries detected in the same scan are bundled
                # into one post instead of one tweet per player.
                injury_changes.append(entry)
            else:
                stories.append({"type": "status_change", "key": f"status:{pid}:{cur['news_added']}", **entry})

    if injury_changes:
        injury_changes.sort(key=lambda c: c["player"])
        batch_key = "injury_batch:" + ",".join(f"{c['pid']}" for c in injury_changes)
        stories.append({
            "type": "injury_batch",
            "key": batch_key,
            "injuries": injury_changes,
        })

    if price_changes:
        # All price changes from the same scan land in one post rather than
        # one tweet per player -- FPL applies price changes to every moved
        # player at once overnight, and a busy night can move a dozen-plus
        # players, which would otherwise blow through the daily post cap on
        # its own and take days to fully get out via the 90-min posting gap.
        price_changes.sort(key=lambda c: (c["direction"], -c["new_price_millions"]))
        batch_key = "price_batch:" + ",".join(f"{c['pid']}:{c['new_price_millions']}" for c in price_changes)
        stories.append({
            "type": "price_changes",
            "key": batch_key,
            "changes": price_changes,
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
    """Only the most recently finished gameweek is worth a recap post -- older
    unrecapped ones are stale by the time we'd get to them, so silently mark
    them recapped (in `state`) without ever generating a story for them."""
    recapped = set(state.get("recapped_events", []))
    unrecapped_finished = sorted(
        ev["id"] for ev in data["events"] if ev["finished"] and ev["id"] not in recapped
    )
    if not unrecapped_finished:
        return []

    *stale, latest = unrecapped_finished
    state.setdefault("recapped_events", [])
    state["recapped_events"].extend(stale)

    ev = next(e for e in data["events"] if e["id"] == latest)
    return [{
        "type": "gw_recap",
        "key": f"recap:{ev['id']}",
        "gw": ev["id"],
        "most_captained": ev.get("most_captained"),
        "highest_score": ev.get("highest_score"),
        "most_selected": ev.get("most_selected"),
    }]


def fetch_stories(state):
    """Mutates `state` in place (snapshot + recap bookkeeping) and returns the
    list of new stories. Caller owns loading/saving `state` -- this function
    must not do its own load_state()/save_state(), or its writes get lost
    whenever the caller also holds and later re-saves its own copy."""
    data = fetch_bootstrap()
    new_snapshot = build_snapshot(data)

    stories = []
    stories += diff_snapshots(state.get("last_snapshot"), new_snapshot)
    stories += deadline_stories(data)
    stories += recap_stories(data, state)

    state["last_snapshot"] = new_snapshot
    state["last_snapshot_at"] = datetime.now(timezone.utc).isoformat()

    return stories


def main():
    """Standalone CLI entrypoint for local testing -- owns its own state
    load/save. orchestrate.py calls fetch_stories() directly instead so
    there's a single load/save per scan run."""
    state = load_state()
    stories = fetch_stories(state)
    save_state(state)
    print(json.dumps(stories, indent=2))
    return stories


if __name__ == "__main__":
    main()

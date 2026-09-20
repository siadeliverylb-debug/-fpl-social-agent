"""Poll the FPL bootstrap-static API and diff against the last-seen snapshot
in state.json to produce a list of "story" dicts worth posting about."""

import hashlib
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


def _batch_key(prefix, parts):
    """The key doubles as the card's filename, so it must stay short no
    matter how many players are in the batch -- listing every player in it
    overflowed the filesystem's filename limit on a big price-change night
    and crashed every scan afterwards."""
    digest = hashlib.sha1(",".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{len(parts)}:{digest}"


# Freshness limits -- better to skip an item than to present old news as new.
MAX_NEWS_AGE_HOURS = 6      # news whose own FPL timestamp is older than this isn't "new"
STALE_SNAPSHOT_HOURS = 3    # a baseline older than this can't tell us what changed *recently*


def _news_is_fresh(news_added, now):
    if not news_added:
        return False  # can't verify its age -> don't call it new
    try:
        added = datetime.fromisoformat(news_added.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - added).total_seconds() <= MAX_NEWS_AGE_HOURS * 3600


def diff_snapshots(old, new, now=None, old_age_hours=None):
    """`old_age_hours` is how long ago `old` was taken. Prices carry no change
    timestamp, so when the baseline is stale (e.g. after a scan outage) a
    price diff would lump days of moves together and present them as "tonight's"
    -- those are skipped. News has its own FPL timestamp, so it's filtered by
    that instead."""
    stories = []
    if old is None:
        return stories  # first run: establish baseline only, nothing to report

    now = now or datetime.now(timezone.utc)
    prices_trustworthy = old_age_hours is None or old_age_hours <= STALE_SNAPSHOT_HOURS

    price_changes = []
    injury_changes = []
    for pid, cur in new.items():
        prev = old.get(pid)
        if prev is None:
            continue  # player not seen before (rare mid-season addition), skip

        if prices_trustworthy and cur["now_cost"] != prev["now_cost"]:
            delta = cur["now_cost"] - prev["now_cost"]
            price_changes.append({
                "pid": pid,
                "player": cur["web_name"],
                "team": cur["team"],
                "direction": "rise" if delta > 0 else "fall",
                "delta_millions": round(abs(delta) / 10, 1),
                "new_price_millions": round(cur["now_cost"] / 10, 1),
            })

        if cur["news"] and cur["news"] != prev["news"] and _news_is_fresh(cur["news_added"], now):
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
        batch_key = _batch_key("injury_batch", [f"{c['pid']}" for c in injury_changes])
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
        batch_key = _batch_key("price_batch", [f"{c['pid']}:{c['new_price_millions']}" for c in price_changes])
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


# Filler content for quiet stretches: when there's no other news, post who's
# in form or struggling instead of leaving the account silent. Alternates
# between the two so consecutive posts differ.
QUIET_HOURS = 3
MAX_SPOTLIGHTS_PER_DAY = 4
SPOTLIGHT_SIZE = 5
SPOTLIGHT_MIN_MINUTES = 180   # ignore players who've barely played
SPOTLIGHT_MIN_OWNERSHIP = 10.0  # "struggling" only counts popular picks
# Filler posts only go out while the (mostly UK/European) audience is awake.
SPOTLIGHT_START_HOUR_UTC = 7
SPOTLIGHT_END_HOUR_UTC = 21  # exclusive: last eligible scan is 20:59 UTC


def _hours_since(iso_ts, now):
    return (now - datetime.fromisoformat(iso_ts)).total_seconds() / 3600


def form_stories(data, state, other_stories, now=None):
    now = now or datetime.now(timezone.utc)

    if not (SPOTLIGHT_START_HOUR_UTC <= now.hour < SPOTLIGHT_END_HOUR_UTC):
        return []

    # Stories like deadline reminders are regenerated every scan and only
    # de-duplicated later, so only count ones that are actually new.
    seen = set(state.get("handled_keys", [])) | {p["key"] for p in state.get("pending", [])}
    if any(s["key"] not in seen for s in other_stories) or state.get("pending"):
        return []  # there's real news to post -- no filler
    log = state.get("post_log", [])
    if log and _hours_since(log[-1]["posted_at"], now) < QUIET_HOURS:
        return []

    fs = state.setdefault("form_spotlight", {"last_at": None, "next": "hot", "day": None, "count": 0})
    if fs["last_at"] and _hours_since(fs["last_at"], now) < QUIET_HOURS:
        return []
    today = now.date().isoformat()
    if fs["day"] != today:
        fs["day"], fs["count"] = today, 0
    if fs["count"] >= MAX_SPOTLIGHTS_PER_DAY:
        return []

    teams = {t["id"]: t["short_name"] for t in data["teams"]}
    rows = []
    for p in data["elements"]:
        if p["minutes"] < SPOTLIGHT_MIN_MINUTES:
            continue
        rows.append({
            "name": p["web_name"],
            "team": teams.get(p["team"], "?"),
            "form": float(p["form"]),
            "total_points": p["total_points"],
            "price_millions": round(p["now_cost"] / 10, 1),
            "selected": float(p["selected_by_percent"]),
        })

    kind = fs["next"]
    if kind == "hot":
        picks = sorted(rows, key=lambda r: (-r["form"], -r["total_points"]))[:SPOTLIGHT_SIZE]
        picks = [r for r in picks if r["form"] > 0]
    else:
        popular = [r for r in rows if r["selected"] >= SPOTLIGHT_MIN_OWNERSHIP]
        picks = sorted(popular, key=lambda r: (r["form"], -r["selected"]))[:SPOTLIGHT_SIZE]
    if len(picks) < 3:
        return []

    fs["last_at"] = now.isoformat()
    fs["next"] = "cold" if kind == "hot" else "hot"
    fs["count"] += 1
    return [{
        "type": "form_hot" if kind == "hot" else "form_cold",
        "key": f"form:{kind}:{now:%Y%m%d%H%M}",
        "players": picks,
    }]


def fetch_stories(state):
    """Mutates `state` in place (snapshot + recap bookkeeping) and returns the
    list of new stories. Caller owns loading/saving `state` -- this function
    must not do its own load_state()/save_state(), or its writes get lost
    whenever the caller also holds and later re-saves its own copy."""
    data = fetch_bootstrap()
    new_snapshot = build_snapshot(data)

    stories = []
    last_at = state.get("last_snapshot_at")
    old_age = _hours_since(last_at, datetime.now(timezone.utc)) if last_at else None
    if old_age is not None and old_age > STALE_SNAPSHOT_HOURS:
        print(f"Previous snapshot is {old_age:.1f}h old -- skipping price changes (can't tell which are recent).")
    stories += diff_snapshots(state.get("last_snapshot"), new_snapshot, old_age_hours=old_age)
    stories += deadline_stories(data)
    stories += recap_stories(data, state)
    stories += form_stories(data, state, stories)

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

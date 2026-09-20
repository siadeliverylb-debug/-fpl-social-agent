"""Entrypoint run by the GitHub Actions workflows.

  python orchestrate.py scan     -- fetch news, draft new stories, queue for Slack review
  python orchestrate.py publish  -- resolve pending drafts (approved / rejected / timed out)
  python orchestrate.py live     -- poll live fixtures, auto-post goals/cards/etc immediately

State (state.json) persists across runs via git commit from the workflow.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import fetch_news
import generate_content
import live_events
import post_instagram
import post_x
import slack_review

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE_PATH = os.path.join(REPO_ROOT, "state.json")
GENERATED_DIR = os.path.join(REPO_ROOT, "assets", "generated")

# Raised from the original 5/day, 90-min gap: real story volume (status
# changes, price-change batches, etc.) was outpacing that cap, leaving a
# growing backlog that took multiple days to drain even after approval --
# e.g. 19 pending items after 2 days against only 8 actually posted. 20/day
# at a 20-min gap comfortably covers the observed ~13-14 stories/day while
# still keeping real spacing between posts.
APPROVAL_TIMEOUT_HOURS = 3
MIN_GAP_MINUTES = 20
MAX_POSTS_PER_DAY = 20

# Live match events (goals/cards/penalties/kickoff/full-time) get their own,
# much looser cadence -- they're only worth posting while still live, and a
# single match day can have far more than 5 FPL-relevant moments. The gap is
# deliberately tiny: real bursts (a goal + a card in the same poll) must not
# get throttled against each other.
LIVE_QUEUE_TTL_MINUTES = 20  # a live event that couldn't post within this is no longer "live"
LIVE_MIN_GAP_SECONDS = 2
LIVE_MAX_POSTS_PER_DAY = 150


def load_state():
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def raw_url_for(rel_path):
    """rel_path is repo-relative (as stored in state), e.g. 'assets/generated/x.png'."""
    repo = os.environ["GITHUB_REPOSITORY"]  # e.g. "owner/repo", set automatically by Actions
    return f"https://raw.githubusercontent.com/{repo}/main/{rel_path}"


def _rel_path(abs_path):
    return os.path.relpath(abs_path, REPO_ROOT).replace(os.sep, "/")


def _abs_path(rel_path):
    return os.path.join(REPO_ROOT, rel_path)


# How long a queued post stays worth publishing. Normally items go out within
# ~an hour; anything older was held up (caps, a failed run) and would now be
# presenting old news as new, so it's dropped rather than posted late.
PENDING_TTL_HOURS = {
    "default": 6,
    "deadline_reminder": 1,   # "deadline in 2h" is wrong an hour later
    "form_hot": 3,
    "form_cold": 3,
    "gw_recap": 24,
}


def is_stale(item, now):
    ttl = PENDING_TTL_HOURS.get(item["story"]["type"], PENDING_TTL_HOURS["default"])
    created = datetime.fromisoformat(item["created_at"])
    return (now - created).total_seconds() > ttl * 3600


def can_post_now(state, now):
    log = state.get("post_log", [])
    if log:
        last_dt = datetime.fromisoformat(log[-1]["posted_at"])
        if (now - last_dt).total_seconds() < MIN_GAP_MINUTES * 60:
            return False
    today = now.date().isoformat()
    count_today = sum(1 for e in log if e["posted_at"].startswith(today))
    return count_today < MAX_POSTS_PER_DAY


def can_post_live_now(state, now):
    log = state.get("live_post_log", [])
    if log:
        last_dt = datetime.fromisoformat(log[-1]["posted_at"])
        if (now - last_dt).total_seconds() < LIVE_MIN_GAP_SECONDS:
            return False
    today = now.date().isoformat()
    count_today = sum(1 for e in log if e["posted_at"].startswith(today))
    return count_today < LIVE_MAX_POSTS_PER_DAY


def cmd_scan(dry_run):
    state = load_state()
    stories = fetch_news.fetch_stories(state)

    handled = set(state.get("handled_keys", []))
    pending_keys = {p["key"] for p in state.get("pending", [])}

    new_count = 0
    for story in stories:
        key = story["key"]
        if key in handled or key in pending_keys:
            continue

        img_path = os.path.join(GENERATED_DIR, f"{key.replace(':', '_')}.png")
        try:
            generate_content.render_card(story, img_path)
            caption = generate_content.build_caption(story)
        except Exception as e:
            # One story that can't be rendered must not take down the whole
            # scan -- a single oversized batch did exactly that for 34 hours.
            print(f"Skipping {key[:60]}: could not render ({type(e).__name__}: {e})")
            continue
        rel_img_path = _rel_path(img_path)

        if state.get("auto_mode"):
            state.setdefault("pending", []).append({
                "key": key,
                "story": story,
                "image_path": rel_img_path,
                "caption": caption,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "auto": True,
            })
        else:
            channel, ts = (None, None)
            if not dry_run:
                channel, ts = slack_review.post_draft(img_path, caption, story)
            state.setdefault("pending", []).append({
                "key": key,
                "story": story,
                "image_path": rel_img_path,
                "caption": caption,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "slack_channel": channel,
                "slack_ts": ts,
                "auto": False,
            })
        new_count += 1

    save_state(state)
    print(f"Scan complete. {new_count} new draft(s) queued.")


def _publish_one(state, item, dry_run, log_key="post_log"):
    story = item["story"]
    img_path = _abs_path(item["image_path"])
    caption = item["caption"]

    x_result = post_x.post_tweet(img_path, caption, dry_run=dry_run)

    if os.environ.get("IG_ACCESS_TOKEN") and os.environ.get("IG_BUSINESS_ACCOUNT_ID"):
        try:
            ig_result = post_instagram.post_image(raw_url_for(item["image_path"]), caption, dry_run=dry_run)
        except Exception as e:
            ig_result = f"FAILED: {e}"
            print(f"Instagram post failed for {item['key']}: {e}")
    else:
        ig_result = "skipped (Instagram not configured)"

    now = datetime.now(timezone.utc)
    tweet_id = x_result.get("id") if isinstance(x_result, dict) else None
    state.setdefault(log_key, []).append({
        "key": item["key"],
        "type": story["type"],
        "posted_at": now.isoformat(),
        "tweet_id": tweet_id,
    })

    if log_key == "post_log":
        state.setdefault("handled_keys", []).append(item["key"])
        if story["type"] == "gw_recap":
            state.setdefault("recapped_events", [])
            if story["gw"] not in state["recapped_events"]:
                state["recapped_events"].append(story["gw"])

    print(f"Published {item['key']}: x={x_result} ig={ig_result}")


def cmd_live(dry_run):
    state = load_state()

    # Items the cadence cap blocked last run go first -- they must never be
    # silently dropped just because the underlying stat counter (which
    # prevents re-detecting the same delta) already advanced past them.
    queue = state.pop("live_queue", [])

    stories = live_events.fetch_live_events(state)
    for story in stories:
        key = story["key"]
        img_path = os.path.join(GENERATED_DIR, f"live_{key.replace(':', '_')}.png")
        generate_content.render_card(story, img_path)
        caption = generate_content.build_caption(story)
        queue.append({
            "key": key, "story": story, "image_path": _rel_path(img_path), "caption": caption,
            "queued_at": datetime.now(timezone.utc).isoformat(),
        })

    now = datetime.now(timezone.utc)
    posted = 0
    still_queued = []
    for item in queue:
        queued_at = item.get("queued_at")
        if queued_at and (now - datetime.fromisoformat(queued_at)).total_seconds() > LIVE_QUEUE_TTL_MINUTES * 60:
            print(f"Dropping stale live event {item['key']} -- older than {LIVE_QUEUE_TTL_MINUTES} min, not posting it late")
            continue
        if not can_post_live_now(state, now):
            print(f"Deferring {item['key']}: live cadence cap hit, will retry next run")
            still_queued.append(item)
            continue
        _publish_one(state, item, dry_run, log_key="live_post_log")
        now = datetime.now(timezone.utc)
        posted += 1

    state["live_queue"] = still_queued
    save_state(state)
    print(f"Live pass complete. {posted}/{len(queue)} event(s) posted, {len(still_queued)} deferred.")


def cmd_publish(dry_run, force=False):
    state = load_state()
    now = datetime.now(timezone.utc)
    still_pending = []

    for item in state.get("pending", []):
        if not force and is_stale(item, now):
            age_h = (now - datetime.fromisoformat(item["created_at"])).total_seconds() / 3600
            print(f"Dropping stale {item['story']['type']} {item['key'][:40]} ({age_h:.1f}h old) -- not posting old news")
            state.setdefault("handled_keys", []).append(item["key"])
            continue

        if item.get("auto"):
            decision = "approved"
        else:
            decision = slack_review.check_status(item["slack_channel"], item["slack_ts"])
            if decision == "pending":
                created = datetime.fromisoformat(item["created_at"])
                if now - created >= timedelta(hours=APPROVAL_TIMEOUT_HOURS):
                    decision = "approved"  # timeout -> auto-publish

        if decision == "rejected":
            state.setdefault("handled_keys", []).append(item["key"])
            continue

        if decision == "approved":
            if force or can_post_now(state, now):
                _publish_one(state, item, dry_run)
            else:
                still_pending.append(item)  # cap/gap hit, retry next run
            continue

        still_pending.append(item)  # still awaiting a reaction

    state["pending"] = still_pending
    save_state(state)
    print(f"Publish pass complete. {len(still_pending)} still pending.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["scan", "publish", "live"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="publish bypassing cadence caps (manual override)")
    args = parser.parse_args()

    if args.mode == "scan":
        cmd_scan(args.dry_run)
    elif args.mode == "publish":
        cmd_publish(args.dry_run, force=args.force)
    else:
        cmd_live(args.dry_run)

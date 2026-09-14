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

APPROVAL_TIMEOUT_HOURS = 3
MIN_GAP_MINUTES = 90
MAX_POSTS_PER_DAY = 5

# Live match events (goals/cards/penalties/kickoff/full-time) get their own,
# much looser cadence -- they're only worth posting while still live, and a
# single match day can have far more than 5 FPL-relevant moments.
LIVE_MIN_GAP_SECONDS = 10
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
        generate_content.render_card(story, img_path)
        caption = generate_content.build_caption(story)
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
    state.setdefault(log_key, []).append({
        "key": item["key"],
        "type": story["type"],
        "posted_at": now.isoformat(),
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
    stories = live_events.fetch_live_events(state)
    now = datetime.now(timezone.utc)

    posted = 0
    for story in stories:
        key = story["key"]
        img_path = os.path.join(GENERATED_DIR, f"live_{key.replace(':', '_')}.png")
        generate_content.render_card(story, img_path)
        caption = generate_content.build_caption(story)
        item = {"key": key, "story": story, "image_path": _rel_path(img_path), "caption": caption}

        if not can_post_live_now(state, now):
            print(f"Skipping {key}: live cadence cap hit")
            continue

        _publish_one(state, item, dry_run, log_key="live_post_log")
        now = datetime.now(timezone.utc)
        posted += 1

    save_state(state)
    print(f"Live pass complete. {posted}/{len(stories)} event(s) posted.")


def cmd_publish(dry_run, force=False):
    state = load_state()
    now = datetime.now(timezone.utc)
    still_pending = []

    for item in state.get("pending", []):
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

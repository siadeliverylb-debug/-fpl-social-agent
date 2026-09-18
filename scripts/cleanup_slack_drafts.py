"""One-off cleanup: now that auto_mode posts new news directly, delete the
old Slack review drafts left over from before that switch, and remove them
from state.json's pending list (marking them handled) so they're not posted
stale and cmd_publish never checks reactions on a now-deleted message.
Temporary script -- delete after use."""
import json
import os

import requests

SLACK_API = "https://slack.com/api"
STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "state.json")


def _token():
    return {"Authorization": f"Bearer {os.environ['SLACK_BOT_TOKEN']}"}


def main():
    with open(STATE_PATH, encoding="utf-8") as f:
        state = json.load(f)

    pending = state.get("pending", [])
    remaining = []
    deleted = 0

    for item in pending:
        channel = item.get("slack_channel")
        ts = item.get("slack_ts")
        if item.get("auto") or not channel or not ts:
            remaining.append(item)
            continue

        resp = requests.post(
            f"{SLACK_API}/chat.delete",
            headers=_token(),
            json={"channel": channel, "ts": ts},
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            deleted += 1
            state.setdefault("handled_keys", []).append(item["key"])
            print(f"Deleted {item['key']} ({channel}:{ts})")
        else:
            print(f"FAILED to delete {item['key']} ({channel}:{ts}): {data}")
            remaining.append(item)

    state["pending"] = remaining

    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print(f"\nDeleted {deleted} draft(s). {len(remaining)} item(s) left in pending.")


if __name__ == "__main__":
    main()

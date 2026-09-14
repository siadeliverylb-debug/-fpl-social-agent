"""Post drafts to Slack for approval and check reaction status.

Requires a Slack bot token (xoxb-...) with scopes: chat:write, reactions:read,
channels:history (or groups:history for a private channel), files:write.
The bot must be invited to the target channel.

Env vars:
  SLACK_BOT_TOKEN
  SLACK_CHANNEL_ID
"""

import os
import requests

SLACK_API = "https://slack.com/api"


def _token():
    tok = os.environ["SLACK_BOT_TOKEN"]
    return {"Authorization": f"Bearer {tok}"}


def _channel():
    return os.environ["SLACK_CHANNEL_ID"]


def post_draft(image_path, caption, story):
    """Uploads the card image with the caption as a comment. Returns (channel, ts)
    of the message so we can check reactions on it later."""
    with open(image_path, "rb") as f:
        resp = requests.post(
            f"{SLACK_API}/files.upload",
            headers=_token(),
            data={
                "channels": _channel(),
                "initial_comment": (
                    f"*New draft: {story['type']}*\n{caption}\n\n"
                    f"React with :white_check_mark: to approve, :x: to reject. "
                    f"Auto-publishes in 3h if no reaction."
                ),
            },
            files={"file": f},
            timeout=30,
        )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack upload failed: {data}")

    file_info = data["file"]
    shares = file_info.get("shares", {})
    ts = None
    for group in ("public", "private"):
        for _chan, msgs in shares.get(group, {}).items():
            if msgs:
                ts = msgs[0]["ts"]
    if ts is None:
        raise RuntimeError(f"Could not determine message ts from Slack response: {data}")

    return _channel(), ts


def check_status(channel, ts):
    """Returns 'approved', 'rejected', or 'pending' based on reactions on the message."""
    resp = requests.get(
        f"{SLACK_API}/reactions.get",
        headers=_token(),
        params={"channel": channel, "timestamp": ts},
        timeout=15,
    )
    data = resp.json()
    if not data.get("ok"):
        if data.get("error") == "no_reaction":
            return "pending"
        raise RuntimeError(f"Slack reactions.get failed: {data}")

    reactions = data.get("message", {}).get("reactions", [])
    names = {r["name"] for r in reactions}

    if names & {"white_check_mark", "heavy_check_mark", "+1", "thumbsup"}:
        return "approved"
    if names & {"x", "-1", "thumbsdown"}:
        return "rejected"
    return "pending"


def notify(text):
    requests.post(
        f"{SLACK_API}/chat.postMessage",
        headers=_token(),
        json={"channel": _channel(), "text": text},
        timeout=15,
    )

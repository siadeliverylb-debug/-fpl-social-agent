"""Post drafts to Slack for approval and check reaction status.

Requires a Slack bot token (xoxb-...) with scopes: chat:write, reactions:read,
files:write. The bot must be invited to the target channel.

Env vars:
  SLACK_BOT_TOKEN
  SLACK_CHANNEL_ID
"""

import os
import time

import requests

SLACK_API = "https://slack.com/api"


def _token():
    tok = os.environ["SLACK_BOT_TOKEN"]
    return {"Authorization": f"Bearer {tok}"}


def _channel():
    return os.environ["SLACK_CHANNEL_ID"]


def post_draft(image_path, caption, story):
    """Uploads the card image (new files.*External flow) with the caption as a
    comment. Returns (channel, ts) of the shared message so we can check
    reactions on it later."""
    filename = os.path.basename(image_path)
    length = os.path.getsize(image_path)

    url_resp = requests.post(
        f"{SLACK_API}/files.getUploadURLExternal",
        headers=_token(),
        data={"filename": filename, "length": length},
        timeout=30,
    )
    url_data = url_resp.json()
    if not url_data.get("ok"):
        raise RuntimeError(f"Slack getUploadURLExternal failed: {url_data}")
    upload_url = url_data["upload_url"]
    file_id = url_data["file_id"]

    with open(image_path, "rb") as f:
        upload_resp = requests.post(
            upload_url, files={"file": (filename, f, "image/png")}, timeout=30
        )
    if upload_resp.status_code != 200:
        raise RuntimeError(f"Slack file upload failed: {upload_resp.status_code} {upload_resp.text}")

    # Slack needs a moment to finish processing the upload (detect mimetype,
    # generate thumbnails) before completeUploadExternal will actually attach
    # it to a channel -- calling immediately silently no-ops the share.
    time.sleep(2)

    complete_resp = requests.post(
        f"{SLACK_API}/files.completeUploadExternal",
        headers={**_token(), "Content-Type": "application/json; charset=utf-8"},
        json={
            "files": [{"id": file_id, "title": filename}],
            "channel_id": _channel(),
            "initial_comment": (
                f"*New draft: {story['type']}*\n{caption}\n\n"
                f"React with :white_check_mark: to approve, :x: to reject. "
                f"Auto-publishes in 3h if no reaction."
            ),
        },
        timeout=30,
    )
    complete_data = complete_resp.json()
    if not complete_data.get("ok"):
        raise RuntimeError(f"Slack completeUploadExternal failed: {complete_data}")

    files = complete_data.get("files", [])
    shares = files[0].get("shares", {}) if files else {}
    ts = None
    for group in ("public", "private"):
        for _chan, msgs in shares.get(group, {}).items():
            if msgs:
                ts = msgs[0]["ts"]
    if ts is None:
        raise RuntimeError(f"Could not determine message ts from Slack response: {complete_data}")

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

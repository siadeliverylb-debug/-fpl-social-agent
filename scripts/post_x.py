"""Post an image + caption to X (Twitter).

Requires OAuth 1.0a user-context credentials for the target account:
  X_API_KEY
  X_API_SECRET
  X_ACCESS_TOKEN
  X_ACCESS_TOKEN_SECRET

Media upload uses X's v2 chunked upload flow (initialize -> append ->
finalize) -- the old v1.1 media/upload.json endpoint tweepy's api.media_upload
hits is no longer accepted ("215 Bad Authentication data") under the newer
pay-per-use API.
"""

import os

import requests
import tweepy
from requests_oauthlib import OAuth1

MEDIA_API = "https://api.x.com/2/media/upload"


def _oauth1():
    return OAuth1(
        os.environ["X_API_KEY"],
        os.environ["X_API_SECRET"],
        os.environ["X_ACCESS_TOKEN"],
        os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def _v2_client():
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def diagnose():
    """Isolate whether OAuth1 auth itself is rejected (account/IP-level issue)
    vs. something specific to the media upload endpoint."""
    auth = _oauth1()
    r = requests.get("https://api.x.com/2/users/me", auth=auth, timeout=30)
    print(f"GET /2/users/me -> {r.status_code} {r.text}")

    r2 = requests.post(
        f"{MEDIA_API}/initialize",
        auth=auth,
        json={"media_type": "image/png", "total_bytes": 100, "media_category": "tweet_image"},
        timeout=30,
    )
    print(f"POST /2/media/upload/initialize -> {r2.status_code} {r2.text}")


def upload_media(image_path):
    auth = _oauth1()
    total_bytes = os.path.getsize(image_path)

    init_resp = requests.post(
        f"{MEDIA_API}/initialize",
        auth=auth,
        json={"media_type": "image/png", "total_bytes": total_bytes, "media_category": "tweet_image"},
        timeout=30,
    )
    if init_resp.status_code >= 400:
        raise RuntimeError(f"media initialize failed: {init_resp.status_code} {init_resp.text}")
    media_id = init_resp.json()["data"]["id"]

    with open(image_path, "rb") as f:
        append_resp = requests.post(
            f"{MEDIA_API}/{media_id}/append",
            auth=auth,
            data={"segment_index": "0"},
            files={"media": f},
            timeout=30,
        )
    if append_resp.status_code >= 400:
        raise RuntimeError(f"media append failed: {append_resp.status_code} {append_resp.text}")

    finalize_resp = requests.post(f"{MEDIA_API}/{media_id}/finalize", auth=auth, timeout=30)
    if finalize_resp.status_code >= 400:
        raise RuntimeError(f"media finalize failed: {finalize_resp.status_code} {finalize_resp.text}")

    return media_id


def post_tweet(image_path, caption, dry_run=False):
    if dry_run:
        print(f"[DRY RUN] Would tweet image={image_path} caption={caption!r}")
        return {"dry_run": True}

    media_id = upload_media(image_path)
    result = _v2_client().create_tweet(text=caption, media_ids=[media_id])
    return result.data


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "diag":
        diagnose()
    else:
        post_tweet(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Test post", dry_run=True)

"""Post an image + caption to X (Twitter).

Requires OAuth 1.0a user-context credentials for the target account (media
upload is not available on OAuth2-only app auth):
  X_API_KEY
  X_API_SECRET
  X_ACCESS_TOKEN
  X_ACCESS_TOKEN_SECRET
"""

import os
import tweepy


def _clients():
    api_key = os.environ["X_API_KEY"]
    api_secret = os.environ["X_API_SECRET"]
    access_token = os.environ["X_ACCESS_TOKEN"]
    access_secret = os.environ["X_ACCESS_TOKEN_SECRET"]

    auth = tweepy.OAuth1UserHandler(api_key, api_secret, access_token, access_secret)
    v1 = tweepy.API(auth)

    v2 = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
    )
    return v1, v2


def post_tweet(image_path, caption, dry_run=False):
    if dry_run:
        print(f"[DRY RUN] Would tweet image={image_path} caption={caption!r}")
        return {"dry_run": True}

    v1, v2 = _clients()
    media = v1.media_upload(filename=image_path)
    result = v2.create_tweet(text=caption, media_ids=[media.media_id])
    return result.data


if __name__ == "__main__":
    import sys
    post_tweet(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Test post", dry_run=True)

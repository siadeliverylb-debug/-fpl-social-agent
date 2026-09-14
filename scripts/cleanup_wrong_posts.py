"""One-off cleanup: delete the 6 bogus 'substitution' tweets posted during the
2026-09-14 baseline-bug flood (see live_events.py fix). Lists candidates by
matching text prefix + a tight timestamp window; only deletes when
CONFIRM_DELETE=true is passed. Temporary script -- delete after use."""

import os
from datetime import datetime, timezone

import tweepy

FLOOD_START = datetime(2026, 9, 14, 20, 43, 0, tzinfo=timezone.utc)
FLOOD_END = datetime(2026, 9, 14, 20, 48, 30, tzinfo=timezone.utc)


def main():
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )
    me = client.get_me()
    user_id = me.data.id
    print(f"Authenticated as user_id={user_id} username={me.data.username}")

    resp = client.get_users_tweets(
        user_id,
        max_results=100,
        tweet_fields=["created_at", "text"],
    )
    tweets = resp.data or []
    print(f"Fetched {len(tweets)} recent tweets.")

    candidates = []
    for t in tweets:
        created = t.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        is_sub_text = t.text.startswith("\U0001F504 SUB!")
        in_window = FLOOD_START <= created <= FLOOD_END
        print(f"  id={t.id} created={created.isoformat()} sub_text={is_sub_text} in_window={in_window} text={t.text[:70]!r}")
        if is_sub_text and in_window:
            candidates.append(t.id)

    print(f"\n{len(candidates)} candidate(s) matched (substitution text + flood time window): {candidates}")

    confirm = os.environ.get("CONFIRM_DELETE", "false").lower() == "true"
    if not confirm:
        print("CONFIRM_DELETE not set -- dry run only, nothing deleted.")
        return

    for tid in candidates:
        result = client.delete_tweet(tid)
        print(f"Deleted {tid}: {result.data}")


if __name__ == "__main__":
    main()

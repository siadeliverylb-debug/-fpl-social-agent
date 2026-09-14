"""Post an image + caption to Instagram via the Graph API Content Publishing flow.

Instagram requires the image at a PUBLIC URL it can fetch (not a local file
upload) -- pass the raw.githubusercontent.com URL of the already-pushed card.

Requires:
  IG_ACCESS_TOKEN         long-lived token for the linked Facebook Page/app
  IG_BUSINESS_ACCOUNT_ID  the Instagram Business Account id (not the @handle)
"""

import os
import time

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"


def post_image(image_url, caption, dry_run=False):
    if dry_run:
        print(f"[DRY RUN] Would post to Instagram image_url={image_url} caption={caption!r}")
        return {"dry_run": True}

    token = os.environ["IG_ACCESS_TOKEN"]
    ig_user_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    create_resp = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    create_data = create_resp.json()
    if "id" not in create_data:
        raise RuntimeError(f"Instagram media create failed: {create_data}")
    creation_id = create_data["id"]

    for _ in range(10):
        status_resp = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=15,
        )
        status = status_resp.json().get("status_code")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram media processing failed: {status_resp.json()}")
        time.sleep(3)

    publish_resp = requests.post(
        f"{GRAPH_API}/{ig_user_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    publish_data = publish_resp.json()
    if "id" not in publish_data:
        raise RuntimeError(f"Instagram publish failed: {publish_data}")

    return publish_data


if __name__ == "__main__":
    import sys
    post_image(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Test post", dry_run=True)

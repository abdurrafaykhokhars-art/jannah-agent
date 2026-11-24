"""At each posting slot: post the oldest approved reel to Instagram through the official
Content Publishing API (upload the file, wait until processed, publish)."""
import time

import requests

from agent.common import (DRY_RUN, ROOT, SETTINGS, apply_approvals, graph, load, notify, now,
                          run_main, save, secret)


def get_video(reel):
    if DRY_RUN:
        return (ROOT / "out" / "videos" / reel["video_file"]).read_bytes()
    r = requests.get(reel["video_url"], timeout=300)
    r.raise_for_status()
    return r.content


def create_container(ig, reel, data):
    base = {"media_type": "REELS", "caption": reel["script"]["caption"], "share_to_feed": "true"}
    if SETTINGS.get("ai_label"):
        base["is_ai_generated"] = "true"
    try:
        c = graph("POST", f"{ig}/media", upload_type="resumable", **base)
    except RuntimeError as e:
        if "is_ai_generated" not in str(e):
            raise
        base.pop("is_ai_generated")
        c = graph("POST", f"{ig}/media", upload_type="resumable", **base)
    if DRY_RUN:
        return c["id"]
    up = requests.post(c["uri"], data=data, timeout=600, headers={
        "Authorization": f"OAuth {secret('META_TOKEN')}", "offset": "0", "file_size": str(len(data))})
    if up.status_code == 200 and up.json().get("success"):
        return c["id"]
    # fall back to letting Instagram download the public GitHub link
    print("upload failed, trying video_url:", up.text[:200])
    return graph("POST", f"{ig}/media", video_url=reel["video_url"], **base)["id"]


def main():
    apply_approvals()
    reels = load("reels", [])
    queue = sorted((r for r in reels if r["status"] == "approved"), key=lambda r: r["made_at"])
    if not queue:
        print("Nothing approved to post right now.")
        return
    reel = queue[0]
    ig = secret("IG_USER_ID")
    container = create_container(ig, reel, get_video(reel))
    for _ in range(40):                                  # up to ~13 minutes
        status = graph("GET", container, fields="status_code").get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            reel["status"] = "failed"
            save("reels", reels)
            raise RuntimeError(f"Instagram could not process reel {reel['reel_id']} ({status}).")
        time.sleep(20)
    else:
        raise RuntimeError(f"Instagram took too long to process reel {reel['reel_id']}; it will retry next slot.")
    media = graph("POST", f"{ig}/media_publish", creation_id=container)
    reel.update(status="published", ig_media_id=media["id"], published_at=now().isoformat())
    save("reels", reels)
    left = len(queue) - 1
    notify(f"📤 Posted: {reel['script']['hook'].replace('*', '')}\n{left} approved reel(s) waiting.")


if __name__ == "__main__":
    run_main("Publish", main)

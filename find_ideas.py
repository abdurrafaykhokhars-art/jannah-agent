"""Weekly: read the latest public reels of your idea pages (official Business Discovery API)
and save new ones, with captions and view counts, to data/sources.json. No videos are downloaded."""
import json
import os

from agent.common import DRY_RUN, ROOT, graph, load, notify, now, run_main, save, secret

FIELDS = ("username,media.limit(25){id,caption,like_count,comments_count,view_count,"
          "permalink,timestamp,media_product_type}")


def pages():
    lines = (ROOT / "idea_pages.txt").read_text(encoding="utf-8").splitlines()
    return [l.strip().lstrip("@") for l in lines if l.strip() and not l.startswith("#")]


def main():
    sources = load("sources", [])
    known = {s["media_id"] for s in sources}
    ig = secret("IG_USER_ID")
    added, failed = 0, []
    for page in pages():
        try:
            if DRY_RUN:
                data = json.loads(os.getenv("DRY_DISCOVERY", "{}"))
            else:
                data = graph("GET", ig, fields=f"business_discovery.username({page}){{{FIELDS}}}")
            posts = data.get("business_discovery", {}).get("media", {}).get("data", [])
        except Exception as e:
            failed.append(f"{page} ({e})")
            continue
        for p in posts:
            if p.get("media_product_type") != "REELS" or p["id"] in known or not p.get("caption"):
                continue
            sources.append({
                "media_id": p["id"], "username": page, "permalink": p.get("permalink"),
                "caption": p["caption"], "likes": p.get("like_count", 0),
                "views": p.get("view_count", 0), "comments": p.get("comments_count", 0),
                "posted_at": p.get("timestamp"), "found_on": now().date().isoformat(), "status": "new",
            })
            known.add(p["id"])
            added += 1
    save("sources", sources)
    waiting = sum(s["status"] == "new" for s in sources)
    msg = f"🔎 Weekly ideas: {added} new reels found. {waiting} ideas waiting to be used."
    if failed:
        msg += "\nCouldn't read: " + "; ".join(failed)[:800] + "\n(Personal accounts can't be read, only Creator or Business.)"
    notify(msg)
    print(msg)


if __name__ == "__main__":
    run_main("Find Ideas", main)

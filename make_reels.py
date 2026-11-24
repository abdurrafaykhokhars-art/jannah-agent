"""Nightly: turn the best unused ideas into original Jannah Leveling reels and send each one
to Telegram with Approve / Decline buttons. Nothing is posted here."""
import json
import os
import sys
import time
from datetime import timedelta
from pathlib import Path

import requests

from agent.common import (DRY_RUN, ROOT, SETTINGS, apply_approvals, load, notify, now,
                          run_main, save, secret, tg)

sys.path.insert(0, str(ROOT / "renderer"))
import render  # noqa: E402

OUT = ROOT / "out" / "videos"
REPO = os.getenv("GITHUB_REPOSITORY", "you/jannah-agent")

RULES = """
You write one original Jannah Leveling reel per request, following the brand file above exactly.
Use the source caption only for its idea and any Quran or hadith it cites. Never copy its wording.
Only use an ayah or hadith you are confident is authentic, with an exact reference (Surah:Ayah, or collection and number). If you are not sure, or the source has no usable idea for the requested pillar, set skip to true and give skip_reason.
Follow the five-beat structure. hook: one line, max 14 words. lesson_1..3: max 12 words each. todays_step: one small action for today, max 14 words.
Wrap one key word in the hook or a lesson line in *asterisks* to highlight it.
level_label format: "LEVEL 0X · PILLAR WORD", e.g. "LEVEL 03 · SALAH".
reference format, uppercase: "QURAN · 2:286" or "ṢAḤĪḤ AL-BUKHĀRĪ · 6465".
arabic: the Arabic text of the ayah or hadith (short part only) with full diacritics, or "" if none.
Pick theme: green for Quran or Sunnah, red for bad habits or wake-up calls, cream for everything else.
verify_link: a quran.com or sunnah.com link for the reference.
caption: the full Instagram caption following the caption template, including hashtags.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {k: {"type": "STRING"} for k in (
        "skip_reason", "pillar", "theme", "level_label", "hook", "lesson_1", "lesson_2", "lesson_3",
        "arabic", "reference", "verify_link", "todays_step", "cta", "caption")},
}
SCHEMA["properties"]["skip"] = {"type": "BOOLEAN"}
SCHEMA["required"] = ["skip", "pillar", "theme", "level_label", "hook", "lesson_1", "lesson_2",
                      "lesson_3", "reference", "verify_link", "todays_step", "cta", "caption"]


def write_script(source, pillar):
    if DRY_RUN:
        s = json.loads((ROOT / "renderer" / "sample.json").read_text(encoding="utf-8"))
        s["pillar"] = pillar
        return s
    brand = (ROOT / "brand" / "brand_jannah.md").read_text(encoding="utf-8")
    body = {
        "system_instruction": {"parts": [{"text": brand + "\n\n" + RULES}]},
        "contents": [{"role": "user", "parts": [{"text":
            f"Pillar: {pillar}\nSource caption: {source['caption']}\nSource views: {source.get('views', 0)}"}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                             "temperature": 0.8},
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{SETTINGS['gemini_model']}:generateContent")
    for attempt in range(4):
        r = requests.post(url, json=body, headers={"x-goog-api-key": secret("GEMINI_API_KEY")}, timeout=120)
        if r.status_code in (429, 500, 503) and attempt < 3:
            time.sleep(20 * (attempt + 1))
            continue
        if r.status_code != 200:
            raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)


def send_for_approval(reel, video):
    chat = secret("TELEGRAM_CHAT_ID")
    s = reel["script"]
    with open(video, "rb") as f:
        tg("sendVideo", files={"video": f}, chat_id=chat, supports_streaming=True,
           caption=f"{reel['slot']} · {s['pillar']}\n{s['reference']}\nCheck: {s.get('verify_link', '')}"[:1000])
    msg = tg("sendMessage", chat_id=chat, disable_web_page_preview=True,
             text=f"Caption:\n\n{s['caption']}"[:4000],
             reply_markup={"inline_keyboard": [[
                 {"text": "✅ Approve", "callback_data": f"a:{reel['reel_id']}"},
                 {"text": "❌ Decline", "callback_data": f"d:{reel['reel_id']}"}]]})
    return msg["message_id"]


def main():
    apply_approvals()
    sources = load("sources", [])
    reels = load("reels", [])
    n = int(SETTINGS["reels_per_day"])
    tomorrow = now() + timedelta(days=1)
    pillars = SETTINGS["pillar_rotation"][tomorrow.strftime("%a")]
    ideas = sorted((s for s in sources if s["status"] == "new"),
                   key=lambda s: s.get("views") or s.get("likes") or 0, reverse=True)
    render.VOICE = SETTINGS.get("voice", render.VOICE)
    OUT.mkdir(parents=True, exist_ok=True)
    used_ids = {r["reel_id"] for r in reels}
    made, skipped, attempts = 0, 0, 0
    for source in ideas:
        if made >= n or attempts >= n * 3:          # protect the free Gemini daily limit
            break
        attempts += 1
        pillar = pillars[made % len(pillars)]
        script = write_script(source, pillar)
        if script.get("skip"):
            source["status"] = "skipped"
            source["skip_reason"] = script.get("skip_reason", "")
            skipped += 1
            continue
        k = made + 1
        while f"{tomorrow:%Y%m%d}-{k}" in used_ids:
            k += 1
        reel_id = f"{tomorrow:%Y%m%d}-{k}"
        used_ids.add(reel_id)
        video = OUT / f"{reel_id}.mp4"
        render.render(script, video)
        reel = {
            "reel_id": reel_id, "for_date": tomorrow.date().isoformat(),
            "slot": SETTINGS["slots"][made] if made < len(SETTINGS["slots"]) else f"Extra {made + 1}",
            "pillar": pillar, "source_permalink": source.get("permalink"), "script": script,
            "video_file": video.name,
            "video_url": f"https://raw.githubusercontent.com/{REPO}/videos/{video.name}",
            "made_at": now().isoformat(), "status": "pending",
        }
        reel["tg_message_id"] = send_for_approval(reel, video)
        reels.append(reel)
        source["status"] = "used"
        made += 1
        save("reels", reels)          # save after each reel so a crash keeps finished work
        save("sources", sources)
    save("reels", reels)
    save("sources", sources)
    left = sum(s["status"] == "new" for s in sources)
    summary = f"🎬 Made {made} reel(s) for {tomorrow:%a %d %b}. Skipped {skipped} weak idea(s). {left} ideas left."
    if made < n:
        summary += "\nNot enough usable ideas: add more pages to idea_pages.txt."
    notify(summary + "\nTap Approve on the ones you want posted.")
    print(summary)


if __name__ == "__main__":
    run_main("Make Reels", main)

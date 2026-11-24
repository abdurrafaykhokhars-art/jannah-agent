"""Shared helpers: settings, saved state, Telegram, Instagram (Meta Graph API)."""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
PKT = timezone(timedelta(hours=5))
GRAPH = "https://graph.facebook.com/v26.0"
DRY_RUN = os.getenv("DRY_RUN") == "1"          # local test mode: no network calls

SETTINGS = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))


def now():
    return datetime.now(PKT)


def secret(name):
    val = os.getenv(name, "")
    if not val and not DRY_RUN:
        raise SystemExit(f"Missing secret {name}. Add it in GitHub: Settings > Secrets and variables > Actions.")
    return val


# ---------- saved state (JSON files committed back to the repo) ----------

def load(name, default):
    p = DATA / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, value):
    (DATA / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Telegram ----------

def tg(method, files=None, **params):
    if DRY_RUN:
        print(f"[telegram] {method}: {str(params)[:160]}")
        if method == "getUpdates":
            return json.loads(os.getenv("DRY_UPDATES", "[]"))
        return {"message_id": 1}
    url = f"https://api.telegram.org/bot{secret('TELEGRAM_BOT_TOKEN')}/{method}"
    if files:
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}
        r = requests.post(url, data=data, files=files, timeout=300)
    else:
        r = requests.post(url, json=params, timeout=60)
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
    return body["result"]


def notify(text):
    try:
        tg("sendMessage", chat_id=secret("TELEGRAM_CHAT_ID"), text=text[:4000],
           disable_web_page_preview=True)
    except Exception as e:  # never let an alert crash the run
        print("could not send Telegram message:", e)


def run_main(name, fn):
    """Run a job; on any error, send the reason to Telegram and fail the run."""
    try:
        fn()
    except Exception as e:
        notify(f"⚠️ {name} failed: {type(e).__name__}: {e}\nOpen GitHub > Actions to see details.")
        raise


# ---------- Instagram (official Graph API) ----------

def graph(method, path, **params):
    if DRY_RUN:
        print(f"[meta] {method} {path} {str(params)[:120]}")
        return {"id": "dry-" + str(int(time.time())), "status_code": "FINISHED", "uri": "dry"}
    params["access_token"] = secret("META_TOKEN")
    r = requests.request(method, f"{GRAPH}/{path}", params=params, timeout=120)
    body = r.json()
    if "error" in body:
        err = body["error"]
        raise RuntimeError(f"Meta API: {err.get('message')} (code {err.get('code')})")
    return body


def sync_decisions():
    """Sync job only: read Approve/Decline taps from Telegram into data/decisions.json.
    (Kept apart from reels.json so jobs running at the same time never overwrite each other.)"""
    state = load("state", {"tg_offset": 0})
    decisions = load("decisions", {})
    reels = {r["reel_id"]: r for r in load("reels", [])}
    chat_id = str(secret("TELEGRAM_CHAT_ID"))
    updates = tg("getUpdates", offset=state["tg_offset"], timeout=0, allowed_updates=["callback_query"])
    new = 0
    for u in updates:
        state["tg_offset"] = u["update_id"] + 1
        cq = u.get("callback_query")
        if not cq or str(cq["from"]["id"]) != chat_id:      # only you can approve
            continue
        action, _, reel_id = cq.get("data", "").partition(":")
        if action not in ("a", "d") or reel_id in decisions:
            continue
        decisions[reel_id] = {"action": "approved" if action == "a" else "rejected", "at": now().isoformat()}
        new += 1
        label = "✅ Approved, it will post at its slot" if action == "a" else "❌ Declined"
        try:
            tg("answerCallbackQuery", callback_query_id=cq["id"], text=label)
        except Exception:
            pass                                             # old taps can't be answered; fine
        msg_id = reels.get(reel_id, {}).get("tg_message_id")
        if msg_id:
            try:
                tg("editMessageReplyMarkup", chat_id=chat_id, message_id=msg_id,
                   reply_markup={"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]})
            except Exception:
                pass
    save("state", state)
    save("decisions", decisions)
    return new


def apply_approvals():
    """Make/Publish jobs: copy your decisions into reels.json; unanswered reels expire after 2 days."""
    reels = load("reels", [])
    decisions = load("decisions", {})
    for r in reels:
        if r["status"] != "pending":
            continue
        d = decisions.get(r["reel_id"])
        if d:
            r["status"], r["decided_at"] = d["action"], d["at"]
        elif now() - datetime.fromisoformat(r["made_at"]) > timedelta(days=2):
            r["status"] = "expired"
    save("reels", reels)
    return reels

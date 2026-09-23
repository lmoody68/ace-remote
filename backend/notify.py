"""
A.C.E. Remote — phone-alert dispatcher.

Turns a monitor alert into a notification on the owner's phone, over any of three channels:
  • push  — ntfy.sh (free/open-source; install the ntfy app, subscribe to your topic → instant push w/ sound)
  • sms   — the carrier's email-to-SMS gateway (no Twilio, no paid service; works on any phone)
  • email — a plain email (shows on the phone's mail app)

SAFE BY DEFAULT: dry-run unless config `enabled: true`. Even when enabled, only `critical`/`warn` alerts
(theft, geofence, overheat, offline) page you — not routine start/stop events. Never raises.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import time
import urllib.request
from email.message import EmailMessage

_HERE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(_HERE, "..", "config.json")
_SMS_GW = {"tmobile": "tmomail.net", "tmo": "tmomail.net", "verizon": "vtext.com", "vzw": "vtext.com",
           "att": "txt.att.net", "sprint": "messaging.sprintpcs.com"}
_PAGE_LEVELS = {"critical", "warn"}
_last_sent: dict[str, float] = {}


def load_config() -> dict:
    try:
        return json.load(open(CONFIG_PATH, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"enabled": False, "channels": [], "cooldown_secs": 30}


def _smtp():
    """Yahoo creds via the JARVIS mail bridge if present, else env (ACE_SMTP_*)."""
    try:
        import sys
        sys.path.insert(0, r"C:\Users\lesli\Documents\JARVIS")
        from bridge import mail
        pw = mail._resolve_app_password(mail.EMAIL)
        if pw:
            return {"host": mail.SMTP_HOST, "port": 465, "user": mail.EMAIL, "pw": pw, "from": mail.EMAIL}
    except Exception:  # noqa: BLE001
        pass
    host, user, pw = os.getenv("ACE_SMTP_HOST"), os.getenv("ACE_SMTP_USER"), os.getenv("ACE_SMTP_PASS")
    if host and user and pw:
        return {"host": host, "port": int(os.getenv("ACE_SMTP_PORT", "465")), "user": user, "pw": pw,
                "from": os.getenv("ACE_SMTP_FROM", user)}
    return None


def _send_email(to_addr: str, subject: str, body: str) -> str:
    s = _smtp()
    if not s:
        return "no SMTP creds"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s["from"], to_addr, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(s["host"], s["port"], context=ssl.create_default_context()) as srv:
        srv.login(s["user"], s["pw"])
        srv.send_message(msg)
    return "sent"


def _send_ntfy(topic: str, title: str, body: str, priority: str = "urgent") -> str:
    url = f"https://ntfy.sh/{topic}"
    # ntfy's Title header is sent as a latin-1 HTTP header — strip emoji / non-encodable chars so urllib
    # doesn't raise (the emoji still shows in the UTF-8 body + the Tags render their own icon).
    safe_title = title.encode("ascii", "ignore").decode("ascii").strip() or "A.C.E. Remote"
    req = urllib.request.Request(url, data=body.encode("utf-8"), method="POST",
                                 headers={"Title": safe_title, "Priority": priority, "Tags": "rotating_light,car"})
    urllib.request.urlopen(req, timeout=8)
    return "sent"


def send_alert(alert: dict, config: dict | None = None, force: bool = False) -> dict:
    """Dispatch one monitor alert to the owner's phone. Returns a result summary (never raises)."""
    cfg = config or load_config()
    level = alert.get("level", "info")
    msg = alert.get("msg", "")
    if not force and level not in _PAGE_LEVELS:
        return {"paged": False, "reason": f"level '{level}' does not page"}

    # cooldown so a flapping sensor can't blast you
    cd = float(cfg.get("cooldown_secs", 30))
    now = time.time()
    if not force and now - _last_sent.get(level, 0) < cd:
        return {"paged": False, "reason": "cooldown"}

    channels = cfg.get("channels", [])
    dry = not cfg.get("enabled", False)
    title = "🚨 A.C.E. Remote" if level == "critical" else "A.C.E. Remote"
    out = {"paged": True, "dry_run": dry, "level": level, "channels": [], "errors": []}

    for ch in channels:
        try:
            if dry:
                out["channels"].append({ch: "DRY-RUN (would send)"}); continue
            if ch == "push" and cfg.get("ntfy_topic"):
                _send_ntfy(cfg["ntfy_topic"], title, msg,
                           "urgent" if level == "critical" else "high")
                out["channels"].append({"push": "sent"})
            elif ch == "sms" and cfg.get("phone") and cfg.get("carrier"):
                gw = _SMS_GW.get(str(cfg["carrier"]).lower())
                digits = "".join(c for c in str(cfg["phone"]) if c.isdigit())
                if gw:
                    out["channels"].append({"sms": _send_email(f"{digits}@{gw}", title, msg)})
            elif ch == "email" and cfg.get("email"):
                out["channels"].append({"email": _send_email(cfg["email"], title + " alert", msg)})
        except Exception as e:  # noqa: BLE001
            out["errors"].append(f"{ch}: {type(e).__name__}: {e}")

    if not dry:
        _last_sent[level] = now
    return out

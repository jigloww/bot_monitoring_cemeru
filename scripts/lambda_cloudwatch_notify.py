"""
AWS Lambda — CloudWatch Alarm → Telegram Notifier
==================================================

Fungsi ini menerima trigger dari SNS yang di-subscribe ke CloudWatch Alarm
dan meneruskan notifikasi ke Telegram.

CARA DEPLOY:
-----------
1. Buka AWS Console → Lambda → Create function
2. Runtime: Python 3.12, Architecture: x86_64
3. Copy seluruh kode ini ke editor Lambda
4. Set Environment Variables:
       TELEGRAM_BOT_TOKEN  = <isi dari .env>
       TELEGRAM_CHAT_ID    = <isi dari .env>
5. Timeout: 10 detik (cukup untuk 1 HTTP request)
6. Tidak perlu layer/dependency tambahan (hanya stdlib)

CARA SETUP SNS + CLOUDWATCH:
----------------------------
Lihat panduan lengkap di: scripts/cloudwatch_setup_guide.md

TRIGGER YANG DIDUKUNG:
----------------------
- EC2 StatusCheckFailed     → VPS ada masalah hardware/OS
- EC2 StatusCheckFailed_System → Masalah infrastruktur AWS
- Custom metric (CPU, RAM)  → Opsional
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


# ==================================================
# STATE MAPPING
# ==================================================

_STATE_ICON = {
    "ALARM":            "🔴",
    "OK":               "🟢",
    "INSUFFICIENT_DATA": "⚠️",
}

_STATE_LABEL = {
    "ALARM":             "ALARM",
    "OK":                "RECOVERED",
    "INSUFFICIENT_DATA": "DATA TIDAK CUKUP",
}


# ==================================================
# LAMBDA HANDLER
# ==================================================

def lambda_handler(event: dict, context) -> dict:
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    # --- Parse pesan dari SNS ---
    sns_record  = event["Records"][0]["Sns"]
    raw_message = sns_record.get("Message", "{}")

    try:
        msg = json.loads(raw_message)
    except json.JSONDecodeError:
        msg = {}

    alarm_name = msg.get("AlarmName",       "Unknown Alarm")
    state      = msg.get("NewStateValue",   "UNKNOWN")
    reason     = msg.get("NewStateReason",  "-")
    region     = msg.get("Region",          "Unknown")

    icon  = _STATE_ICON.get(state,  "⚠️")
    label = _STATE_LABEL.get(state, state)

    # --- Build Telegram message ---
    text = "\n".join([
        f"{icon} VPS {label}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"🔔 Alarm   : {alarm_name}",
        f"📊 Status  : {state}",
        f"🌏 Region  : {region}",
        "",
        "📄 Detail",
        reason[:300],  # Batasi panjang pesan
        "",
        "━━━━━━━━━━━━━━━━━━",
        "",
        ("⚠️ Monitoring Semeru mungkin tidak aktif. Periksa VPS segera."
         if state == "ALARM" else
         "✅ VPS kembali normal. Monitoring Semeru aktif kembali."),
    ])

    # --- Kirim ke Telegram ---
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":                  chat_id,
        "text":                     text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")

    return {"statusCode": 200, "body": "OK"}

#!/bin/bash
# =============================================================
# notify_failure.sh
# Kirim notifikasi Telegram ketika semeru-bot.service gagal
# restart dan masuk state "failed".
#
# Dipanggil oleh: semeru-bot-failure.service (systemd OnFailure)
# =============================================================

ENV_FILE="/home/ubuntu/semeru_bot/.env"

# --- Baca token & chat_id dari .env ---
if [[ -f "$ENV_FILE" ]]; then
    TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" \
        | cut -d'=' -f2 | tr -d '\r\n "'"'"')
    CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "$ENV_FILE" \
        | cut -d'=' -f2 | tr -d '\r\n "'"'"')
fi

if [[ -z "$TOKEN" || -z "$CHAT_ID" ]]; then
    echo "[notify_failure] ERROR: TOKEN atau CHAT_ID tidak ditemukan di $ENV_FILE" >&2
    exit 1
fi

HOSTNAME_VAL=$(hostname)
TIMESTAMP=$(date '+%d-%m-%Y %H:%M:%S UTC')

MESSAGE="🚨 SERVICE FAILURE

━━━━━━━━━━━━━━━━━━

semeru-bot.service berhenti dan gagal di-restart oleh systemd.

🖥 Server  : ${HOSTNAME_VAL}
🕒 Waktu   : ${TIMESTAMP}

━━━━━━━━━━━━━━━━━━

⚠️ Monitoring Semeru TIDAK aktif.
Periksa VPS segera."

# --- Kirim ke Telegram ---
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" \
    --data-urlencode "text=${MESSAGE}" \
    -d "disable_web_page_preview=true")

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "[notify_failure] Notifikasi Telegram terkirim (HTTP 200)"
else
    echo "[notify_failure] Gagal kirim Telegram (HTTP ${HTTP_STATUS})" >&2
    exit 1
fi

exit 0

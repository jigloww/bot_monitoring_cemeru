"""
Semeru Quota Bot — Entry Point

Push Message yang aktif:
    ✅ Morning Report (08:00 WIB)
    ✅ Night Report   (22:00 WIB)
    ✅ Website Error  (sekali per incident, dengan penyebab spesifik)
    ✅ Monitoring Suspended (sekali per incident)
    ✅ Website Recovery (sekali per incident)
    ✅ Quota Alert (kuota baru / naik / turun / habis)

Push Message yang dinonaktifkan:
    ❌ Startup Message
    ❌ Daily Heartbeat
    ❌ Bot Running Notification

Pull Message:
    ✅ /status — status bot, website (spesifik), uptime, last check, slot
"""
from __future__ import annotations

import argparse
import time

from datetime import datetime

from bot.config         import load_dotenv, get_config
from bot.constants      import LOCAL_TZ
from bot.logger         import logger
from bot.messages       import (
    build_change_messages,
    build_daily_report,
    build_error_message,
    build_recovery_message,
    build_suspended_message,
)
from bot.monitor        import get_current_slots, resolve_months
from bot.scheduler      import should_send_morning_report, should_send_night_report
from bot.state          import load_state, save_state
from bot.telegram       import send_message, start_polling
from bot.website_status import WebsiteError, WebsiteStatus


# ==================================================
# MAIN LOOP
# ==================================================

def run_bot(args: argparse.Namespace) -> None:

    load_dotenv()
    cfg = get_config()

    logger.info(
        f"Bot started — interval={cfg.interval_seconds}s "
        f"max_months={cfg.max_months}"
    )

    # Catat startup_time ke state agar tersedia untuk /status
    _state = load_state()
    _state["startup_time"] = datetime.now(LOCAL_TZ).isoformat()
    save_state(_state)
    del _state

    # Jalankan polling thread (Pull Message) sebagai daemon
    start_polling(cfg.token, cfg.chat_id)

    # --------------------------------------------------
    # Monitoring loop
    # --------------------------------------------------

    while True:

        now            = datetime.now(LOCAL_TZ)
        website_status = WebsiteStatus.NORMAL

        # Baca state di awal setiap siklus
        state = load_state()

        # Fallback: gunakan data terakhir yang tersimpan jika request gagal
        current_slots = state.get("slots", {})
        months        = state.get("months", [])

        try:
            # ----------------------------------------
            # Ambil data website
            # ----------------------------------------
            months        = resolve_months(cfg.check_months, cfg.max_months)
            current_slots = get_current_slots(months)

            logger.info(
                f"Monitoring {months} | "
                f"Found {len(current_slots)} available slots"
            )

            previous_slots = state.get("slots", {})

            # ----------------------------------------
            # 1. QUOTA ALERT
            # ----------------------------------------
            for message in build_change_messages(previous_slots, current_slots):
                send_message(cfg.token, cfg.chat_id, message)
                logger.info("[ALERT] Quota change message sent")

            # ----------------------------------------
            # 2. RECOVERY (error → normal)
            # ----------------------------------------
            if state.get("error", {}).get("active"):
                send_message(
                    cfg.token, cfg.chat_id,
                    build_recovery_message(now),
                )
                state["error"]["active"]         = False
                state["error"]["last_error"]      = ""
                state["error"]["website_status"]  = WebsiteStatus.NORMAL.value
                logger.info("Recovery message sent — monitoring resumed")

            # Simpan data terbaru
            state["slots"]  = current_slots
            state["months"] = months
            state["error"].setdefault("website_status", WebsiteStatus.NORMAL.value)
            state["error"]["website_status"] = WebsiteStatus.NORMAL.value

        except WebsiteError as exc:
            website_status = exc.status
            logger.error(
                f"Website error [{website_status.value}]: {exc.detail}"
            )
            state.setdefault("error", {
                "active":         False,
                "last_error":     "",
                "website_status": WebsiteStatus.NORMAL.value,
            })

            # ----------------------------------------
            # 3. WEBSITE ERROR + SUSPENDED (sekali per incident)
            # ----------------------------------------
            if not state["error"].get("active", False):
                send_message(
                    cfg.token, cfg.chat_id,
                    build_error_message(website_status, now),
                )
                send_message(
                    cfg.token, cfg.chat_id,
                    build_suspended_message(website_status, now),
                )
                state["error"]["active"]         = True
                state["error"]["last_error"]      = str(exc)
                state["error"]["website_status"]  = website_status.value
                logger.info(
                    f"Error + Suspended messages sent [{website_status.value}]"
                )

        except Exception as exc:
            website_status = WebsiteStatus.UNKNOWN
            logger.error(f"Unexpected error: {exc}")
            state.setdefault("error", {
                "active":         False,
                "last_error":     "",
                "website_status": WebsiteStatus.NORMAL.value,
            })

            if not state["error"].get("active", False):
                send_message(
                    cfg.token, cfg.chat_id,
                    build_error_message(website_status, now),
                )
                send_message(
                    cfg.token, cfg.chat_id,
                    build_suspended_message(website_status, now),
                )
                state["error"]["active"]         = True
                state["error"]["last_error"]      = str(exc)
                state["error"]["website_status"]  = website_status.value
                logger.info("Error + Suspended messages sent [UNKNOWN]")

        # ----------------------------------------
        # last_check_time selalu diperbarui (sukses maupun gagal)
        # agar user tahu bot masih hidup (req H)
        # ----------------------------------------
        state["last_check_time"] = now.isoformat()

        # ----------------------------------------
        # 4. MORNING REPORT — selalu dicek, meski website error
        # ----------------------------------------
        if should_send_morning_report(state, now):
            send_message(
                cfg.token, cfg.chat_id,
                build_daily_report(
                    "🌅 CEMERU MORNING REPORT",
                    months,
                    current_slots,
                    website_status,
                ),
            )
            state.setdefault("reports", {})["morning"] = (
                now.strftime("%Y-%m-%d")
            )
            logger.info(f"Morning report sent [{website_status.value}]")

        # ----------------------------------------
        # 5. NIGHT REPORT — selalu dicek, meski website error
        # ----------------------------------------
        if should_send_night_report(state, now):
            send_message(
                cfg.token, cfg.chat_id,
                build_daily_report(
                    "🌙 CEMERU NIGHT REPORT",
                    months,
                    current_slots,
                    website_status,
                ),
            )
            state.setdefault("reports", {})["night"] = (
                now.strftime("%Y-%m-%d")
            )
            logger.info(f"Night report sent [{website_status.value}]")

        save_state(state)

        if args.once:
            logger.info("--once flag set, exiting")
            return

        time.sleep(cfg.interval_seconds)


# ==================================================
# ARGPARSE
# ==================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Semeru Quota Bot — Monitoring & Alert"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Jalankan sekali lalu berhenti (untuk testing)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    run_bot(parse_args())

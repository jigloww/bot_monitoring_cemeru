from __future__ import annotations

import argparse
import time

from datetime import datetime

from bot.config    import load_dotenv, get_config
from bot.constants import LOCAL_TZ
from bot.logger    import logger
from bot.messages  import (
    build_change_messages,
    build_daily_report,
    build_error_message,
    build_recovery_message,
)
from bot.monitor   import get_current_slots, resolve_months
from bot.scheduler import (
    should_send_morning_report,
    should_send_night_report,
)
from bot.state     import load_state, save_state
from bot.telegram  import send_message, start_polling


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

    # Jalankan polling thread (Pull Message)
    start_polling(cfg.token, cfg.chat_id)

    # --------------------------------------------------
    # Monitoring loop
    # --------------------------------------------------

    while True:

        now = datetime.now(LOCAL_TZ)

        try:
            months        = resolve_months(cfg.check_months, cfg.max_months)
            current_slots = get_current_slots(months)

            logger.info(
                f"Monitoring {months} | "
                f"Found {len(current_slots)} available slots"
            )

            state          = load_state()
            previous_slots = state.get("slots", {})

            # ----------------------------------------
            # 1. QUOTA ALERT
            # ----------------------------------------
            for message in build_change_messages(previous_slots, current_slots):
                send_message(cfg.token, cfg.chat_id, message)
                logger.info("[ALERT] Quota change message sent")

            # ----------------------------------------
            # 2. MORNING REPORT
            # ----------------------------------------
            if should_send_morning_report(state, now):
                send_message(
                    cfg.token, cfg.chat_id,
                    build_daily_report(
                        "🌅 CEMERU MORNING REPORT",
                        months,
                        current_slots,
                    ),
                )
                state.setdefault("reports", {})["morning"] = (
                    now.strftime("%Y-%m-%d")
                )
                logger.info("Morning report sent")

            # ----------------------------------------
            # 3. NIGHT REPORT
            # ----------------------------------------
            if should_send_night_report(state, now):
                send_message(
                    cfg.token, cfg.chat_id,
                    build_daily_report(
                        "🌙 CEMERU NIGHT REPORT",
                        months,
                        current_slots,
                    ),
                )
                state.setdefault("reports", {})["night"] = (
                    now.strftime("%Y-%m-%d")
                )
                logger.info("Night report sent")

            # ----------------------------------------
            # 4. RECOVERY (error → normal)
            # ----------------------------------------
            if state.get("error", {}).get("active"):
                send_message(cfg.token, cfg.chat_id, build_recovery_message(now))
                state["error"]["active"]     = False
                state["error"]["last_error"] = ""
                logger.info("Recovery message sent — monitoring resumed")

            # ----------------------------------------
            # Simpan state terbaru
            # ----------------------------------------
            state["slots"]           = current_slots
            state["months"]          = months
            state["last_check_time"] = now.isoformat()
            save_state(state)

        except Exception as exc:

            error_text = str(exc)
            logger.error(f"Monitor error: {error_text}")

            state = load_state()
            state.setdefault("error", {"active": False, "last_error": ""})

            # ----------------------------------------
            # 5. WEBSITE ERROR (dikirim sekali per incident)
            # ----------------------------------------
            if not state["error"]["active"]:
                send_message(
                    cfg.token, cfg.chat_id,
                    build_error_message(error_text, now),
                )
                state["error"]["active"]     = True
                state["error"]["last_error"] = error_text
                save_state(state)
                logger.info("Error message sent — will retry automatically")

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


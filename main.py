"""
Interactive Telegram bot entry point.

/start shows a button menu:
  - Top Recommendations  -> best single picks for matches kicking off in the
                             next WINDOW_HOURS from the moment you click
  - Parlay Suggestions   -> multi-leg combos built from those same picks

Runs as a long-polling bot, which works fine inside a Render Background Worker
(no webhook / public URL needed).
"""

import os
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from betting_framework import BettingFramework, build_parlays
from odds_client import OddsClient
from bot import format_recommendation, format_parlay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

WINDOW_HOURS = int(os.environ.get("WINDOW_HOURS", 12))
_sport_keys_raw = os.environ.get("SPORT_KEYS", "soccer_argentina_primera_division").strip()
SCAN_ALL_LEAGUES = _sport_keys_raw.lower() == "all"
SPORT_KEYS = [] if SCAN_ALL_LEAGUES else [s.strip() for s in _sport_keys_raw.split(",")]
MIN_CONFIDENCE = int(os.environ.get("MIN_CONFIDENCE", 55))
MAX_RESULTS = int(os.environ.get("MAX_RESULTS", 8))

odds_client = OddsClient()
_classifier = BettingFramework(league_type="normal")  # only used for classify_league()

MENU_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🎯 Top Recommendations", callback_data="top_recs")],
    [InlineKeyboardButton("🎲 Parlay Suggestions", callback_data="parlays")],
])

BACK_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔙 Menu", callback_data="menu")],
])

LEAGUE_LABEL = "all active leagues" if SCAN_ALL_LEAGUES else ", ".join(SPORT_KEYS)


async def get_picks() -> list:
    """Fetch matches in the next WINDOW_HOURS and evaluate each one. Blocking
    network calls run in a thread so they don't stall the bot's event loop."""
    matches = await asyncio.to_thread(
        odds_client.get_matches_in_window,
        None if SCAN_ALL_LEAGUES else SPORT_KEYS,
        WINDOW_HOURS,
        "eu", "h2h,totals",
        SCAN_ALL_LEAGUES,
    )

    log.info(f"[diag] fetched {len(matches)} match(es) inside the {WINDOW_HOURS}h window")

    skip_count = 0
    below_conf_count = 0
    picks = []
    for match in matches:
        league_type = _classifier.classify_league(match["league_name"])
        framework = BettingFramework(league_type=league_type, league_name=match["league_name"])
        decision = framework.evaluate_match(
            match["home_odds"], match["draw_odds"], match["away_odds"],
            over_odds=match.get("over_odds"), under_odds=match.get("under_odds"),
        )

        log.info(
            f"[diag] {match['home_team']} vs {match['away_team']} "
            f"({match['league_name']}, kicks off {match['commence_time']}, "
            f"classified as '{league_type}') -> level={decision['level']}, "
            f"confidence={decision['confidence']}, edge={decision['edge']:.3f}"
        )

        if decision["level"] == "SKIP":
            skip_count += 1
            continue
        if decision["confidence"] < MIN_CONFIDENCE:
            below_conf_count += 1
            continue
        picks.append({"match": match, "decision": decision})

    log.info(
        f"[diag] {len(matches)} fetched -> {skip_count} SKIP, "
        f"{below_conf_count} below {MIN_CONFIDENCE}% confidence, "
        f"{len(picks)} qualifying pick(s)"
    )

    picks.sort(key=lambda p: p["decision"]["confidence"], reverse=True)
    return picks


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Betting picks bot. Scanning matches kicking off in the next {WINDOW_HOURS}h.\n"
        f"Leagues: {LEAGUE_LABEL}\n\nChoose an option:",
        reply_markup=MENU_KEYBOARD,
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"Betting picks bot. Scanning matches kicking off in the next {WINDOW_HOURS}h.\n"
        f"Leagues: {LEAGUE_LABEL}\n\nChoose an option:",
        reply_markup=MENU_KEYBOARD,
    )


async def top_recs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Scanning odds...")
    await query.edit_message_text(f"Scanning matches for the next {WINDOW_HOURS}h...")

    try:
        picks = await get_picks()
    except Exception as e:
        log.exception("top_recs failed")
        await query.edit_message_text(f"Couldn't fetch odds right now ({e}).", reply_markup=BACK_KEYBOARD)
        return

    if not picks:
        await query.edit_message_text(
            f"No qualifying picks in the next {WINDOW_HOURS}h (nothing cleared "
            f"{MIN_CONFIDENCE}% confidence).",
            reply_markup=BACK_KEYBOARD,
        )
        return

    top = picks[:MAX_RESULTS]
    blocks = [format_recommendation(p["match"], p["decision"], i + 1) for i, p in enumerate(top)]
    text = f"*Top Recommendations* (next {WINDOW_HOURS}h)\n\n" + "\n\n".join(blocks)

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=BACK_KEYBOARD)


async def parlays_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Building parlays...")
    await query.edit_message_text(f"Scanning matches for the next {WINDOW_HOURS}h...")

    try:
        picks = await get_picks()
    except Exception as e:
        log.exception("parlays failed")
        await query.edit_message_text(f"Couldn't fetch odds right now ({e}).", reply_markup=BACK_KEYBOARD)
        return

    # One leg per match only -- build_parlays assumes independent matches.
    seen_matches = set()
    unique_picks = []
    for p in picks:
        key = (p["match"]["home_team"], p["match"]["away_team"], p["match"]["commence_time"])
        if key in seen_matches:
            continue
        seen_matches.add(key)
        unique_picks.append(p)

    parlays = build_parlays(unique_picks)

    if not parlays:
        await query.edit_message_text(
            f"Not enough independent picks in the next {WINDOW_HOURS}h to build a parlay "
            f"(need at least 2 matches clearing {MIN_CONFIDENCE}% confidence).",
            reply_markup=BACK_KEYBOARD,
        )
        return

    blocks = [format_parlay(p, i + 1) for i, p in enumerate(parlays)]
    text = f"*Parlay Suggestions* (next {WINDOW_HOURS}h)\n\n" + "\n\n".join(blocks)
    text += "\n\n_Combined odds assume independent legs -- correlated outcomes (e.g. same league, same day) can move together._"

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=BACK_KEYBOARD)


def main():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise ValueError("Set TELEGRAM_TOKEN as an environment variable.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(top_recs_callback, pattern="^top_recs$"))
    app.add_handler(CallbackQueryHandler(parlays_callback, pattern="^parlays$"))

    log.info(f"Starting bot. Window={WINDOW_HOURS}h, leagues={LEAGUE_LABEL}, min_confidence={MIN_CONFIDENCE}")

    # Render sets RENDER_EXTERNAL_URL automatically on Web Services (not on
    # Background Workers, and not present when running locally). Use that as
    # the signal to switch modes: webhook when deployed on Render's free Web
    # Service tier, long polling for local development.
    external_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_URL")

    if external_url:
        port = int(os.environ.get("PORT", 10000))
        url_path = token  # use the bot token as an unguessable path segment
        webhook_url = f"{external_url.rstrip('/')}/{url_path}"

        log.info(f"Running in webhook mode: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=url_path,
            webhook_url=webhook_url,
            secret_token=os.environ.get("WEBHOOK_SECRET") or None,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        log.info("No RENDER_EXTERNAL_URL/WEBHOOK_URL set -- running in long-polling mode (local dev).")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

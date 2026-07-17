import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from odds_fetcher import OddsFetcher, OddsAPIError
from analyzer import MatchAnalyzer
from parlay_builder import ParlayBuilder
from time_utils import format_kickoff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🎯 *Commands*\n"
    "/check — build today's parlay\n"
    "/matches — list today's soccer matches (add a page number for more, e.g. /matches 2)\n"
    "/leagues — list leagues currently being scanned\n"
    "/ping — check the bot is alive\n\n"
    "⚠️ Bet responsibly."
)


class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # keep this out of the app logs; it's just Render's port probe


def _start_health_check_server():
    """Render's free Web Service tier expects something bound to $PORT,
    or it eventually times out the deploy. This bot has no real web
    traffic (it's a Telegram poller), so this just answers 200 OK to
    keep Render's port scan happy, in a background thread."""
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health-check server listening on port %s", port)


class BettingBot:
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.odds_fetcher = OddsFetcher()
        self.analyzer = MatchAnalyzer()
        self.parlay_builder = ParlayBuilder()

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("check", self.check))
        self.app.add_handler(CommandHandler("matches", self.matches))
        self.app.add_handler(CommandHandler("leagues", self.leagues))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("ping", self.ping))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎯 *Betting Bot Active!*\n\n" + HELP_TEXT, parse_mode="Markdown"
        )

    async def check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Fetching and analyzing today's soccer matches...")

        try:
            matches = self.odds_fetcher.fetch_todays_matches()
        except OddsAPIError as e:
            logger.error("OddsAPIError in /check: %s", e)
            await update.message.reply_text(f"❌ Couldn't fetch odds: {e}")
            return

        if not matches:
            await update.message.reply_text("⚠️ No soccer matches found in the next 24 hours.")
            return

        analyzed = self.analyzer.analyze_matches(matches)
        parlay = self.parlay_builder.build_parlay(analyzed)
        message = self.parlay_builder.format_message(parlay, total_analyzed=len(analyzed))
        # No parse_mode here: team names can contain characters (., -, etc.)
        # that break Telegram's legacy Markdown parser and silently fail to send.
        await update.message.reply_text(message)

    async def matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        page = 1
        if context.args:
            try:
                page = max(1, int(context.args[0]))
            except ValueError:
                await update.message.reply_text("Usage: /matches or /matches 2 (for page 2, etc.)")
                return

        await update.message.reply_text("🔍 Fetching today's matches...")

        try:
            matches = self.odds_fetcher.fetch_todays_matches()
        except OddsAPIError as e:
            logger.error("OddsAPIError in /matches: %s", e)
            await update.message.reply_text(f"❌ Couldn't fetch odds: {e}")
            return

        if not matches:
            await update.message.reply_text("⚠️ No soccer matches found in the next 24 hours.")
            return

        PAGE_SIZE = 25
        total_pages = max(1, (len(matches) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * PAGE_SIZE
        page_matches = matches[start:start + PAGE_SIZE]

        lines = [f"📊 Today's Matches (times in WAT) — page {page}/{total_pages}\n"]
        stats = self.odds_fetcher.last_run_stats
        if stats.get("leagues_failed"):
            lines.append(
                f"⚠️ {stats['leagues_failed']}/{stats['leagues_total']} leagues failed to load "
                f"(likely API quota) — results may be incomplete.\n"
            )

        for i, match in enumerate(page_matches, start + 1):
            odds = match["odds"]
            kickoff = format_kickoff(match.get("commence_time"))
            lines.append(
                f"{i}. {match['home_team']} vs {match['away_team']} ({match['league']})\n"
                f"   {kickoff}\n"
                f"   {odds['home']:.2f} | {odds['draw']:.2f} | {odds['away']:.2f}"
            )

        if page < total_pages:
            lines.append(f"\nSend /matches {page + 1} for the next page ({len(matches) - start - PAGE_SIZE} more).")

        await update.message.reply_text("\n".join(lines))

    async def leagues(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            leagues = self.odds_fetcher.get_active_leagues()
        except OddsAPIError as e:
            logger.error("OddsAPIError in /leagues: %s", e)
            await update.message.reply_text(f"❌ Couldn't fetch leagues: {e}")
            return

        if not leagues:
            await update.message.reply_text("⚠️ No active soccer leagues returned by the API.")
            return

        lines = ["🌍 *Active Soccer Leagues*\n"]
        lines.extend(f"• {league['title']}" for league in leagues)
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🏓 Pong! Bot is alive.")

    def run(self):
        _start_health_check_server()
        logger.info("Bot is running...")
        self.app.run_polling()


if __name__ == "__main__":
    bot = BettingBot()
    bot.run()

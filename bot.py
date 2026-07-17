import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import TELEGRAM_BOT_TOKEN
from odds_fetcher import OddsFetcher, OddsAPIError
from analyzer import MatchAnalyzer
from parlay_builder import ParlayBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

HELP_TEXT = (
    "🎯 *Commands*\n"
    "/check — build today's parlay\n"
    "/matches — list today's soccer matches\n"
    "/leagues — list leagues currently being scanned\n"
    "/ping — check the bot is alive\n\n"
    "⚠️ Bet responsibly."
)


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

        lines = ["📊 Today's Matches\n"]
        for i, match in enumerate(matches[:25], 1):
            odds = match["odds"]
            lines.append(
                f"{i}. {match['home_team']} vs {match['away_team']} ({match['league']})\n"
                f"   {odds['home']:.2f} | {odds['draw']:.2f} | {odds['away']:.2f}"
            )
        if len(matches) > 25:
            lines.append(f"\n…and {len(matches) - 25} more.")

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
        logger.info("Bot is running...")
        self.app.run_polling()


if __name__ == "__main__":
    bot = BettingBot()
    bot.run()

import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import traceback

from config import TELEGRAM_BOT_TOKEN
from odds_fetcher import OddsFetcher
from analyzer import MatchAnalyzer
from parlay_builder import ParlayBuilder

logging.basicConfig(level=logging.INFO)

class BettingBot:
    def __init__(self):
        self.app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        self.odds_fetcher = OddsFetcher()
        self.analyzer = MatchAnalyzer()
        self.parlay_builder = ParlayBuilder()

        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("check", self.check))
        self.app.add_handler(CommandHandler("matches", self.matches))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CommandHandler("ping", self.ping))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"🎯 **Betting Bot Active!**\n\nCommands:\n/check - Get parlay\n/matches - View matches\n/help - Help\n/ping - Check status",
            parse_mode="Markdown"
        )

    async def check(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Fetching and analyzing...")

        try:
            matches = self.odds_fetcher.fetch_todays_matches()
            if not matches:
                await update.message.reply_text("⚠️ No matches found.")
                return

            analyzed = self.analyzer.analyze_matches(matches)
            parlay = self.parlay_builder.build_parlay(analyzed)
            message = self.parlay_builder.format_message(parlay)
            await update.message.reply_text(message, parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def matches(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🔍 Fetching matches...")

        try:
            matches = self.odds_fetcher.fetch_todays_matches()
            if not matches:
                await update.message.reply_text("⚠️ No matches.")
                return

            message = "📊 **Today's Matches**\n\n"
            for i, match in enumerate(matches[:10], 1):
                odds = match.get("odds", {})
                message += f"{i}. {match.get('home_team')} vs {match.get('away_team')}\n"
                message += f"   {odds.get('home', 0):.2f} | {odds.get('draw', 0):.2f} | {odds.get('away', 0):.2f}\n\n"

            await update.message.reply_text(message, parse_mode="Markdown")

        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🎯 **Commands:**\n/check - Get parlay\n/matches - View matches\n/ping - Check status\n\n⚠️ Bet responsibly."
        )

    async def ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🏓 Pong! Bot is alive.")

    def run(self):
        print("🤖 Bot is running...")
        self.app.run_polling()

if __name__ == "__main__":
    bot = BettingBot()
    bot.run()
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

MIN_ODDS = 1.20
MAX_ODDS = 2.20
TARGET_ODDS = 1.75
CONFIDENCE_THRESHOLD = 7
MAX_PARLAY_LEGS = 4
import os
from dotenv import load_dotenv

load_dotenv()

# --- Secrets (set these in Render's Environment tab, not in code) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set (check your environment variables).")
if not ODDS_API_KEY:
    raise RuntimeError("ODDS_API_KEY is not set (check your environment variables).")

# --- Odds filtering: 1X2 (Home/Away Win) ---
MIN_ODDS = 1.20
MAX_ODDS = 2.20

# --- Odds filtering: Over 2.5 Goals ---
OVER25_MIN_ODDS = 1.20
OVER25_MAX_ODDS = 1.80
OVER25_LOW_ODDS_BONUS_THRESHOLD = 1.50   # below this, treated as "bookmaker expects goals"

# --- Confidence scoring inputs ---
DRAW_GAP_THRESHOLD = 0.10         # min true-prob gap over Draw to consider Home/Away a "clear" pick
LOW_MARGIN_THRESHOLD = 0.08       # bookmaker margin below this counts as "efficient odds"
MISMATCH_ODDS_THRESHOLD = 1.30    # favorite odds below this = "massive mismatch"

# --- Parlay building ---
CONFIDENCE_THRESHOLD = 7          # out of 10, minimum to be considered "safe" enough
MAX_PARLAY_LEGS = 4
BANKROLL_STAKE_PCT = 5            # suggested stake as % of bankroll

# --- Odds API ---
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
ODDS_API_REGIONS = "eu"
ODDS_API_MARKETS = "h2h,totals"   # totals needed for Over/Under 2.5 Goals
ODDS_API_ODDS_FORMAT = "decimal"

# How long to cache the list of active soccer leagues and fetched matches,
# to avoid burning through the-odds-api's monthly request quota.
LEAGUE_LIST_CACHE_SECONDS = 6 * 60 * 60   # 6 hours
MATCHES_CACHE_SECONDS = 15 * 60           # 15 minutes

# Only show matches starting within this many hours from now (i.e. "today")
MATCH_WINDOW_HOURS = 12

# Timezone used to display kickoff times to the user (WAT, UTC+1, no DST)
DISPLAY_TIMEZONE = "Africa/Lagos"

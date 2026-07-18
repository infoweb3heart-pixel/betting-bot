# main.py
#
# Telegram bot that builds a low-risk 4-leg parlay from live soccer odds.
# Everything lives in this ONE file on purpose — no subfolders, no local
# imports to break. Just this file + requirements.txt.
#
# IMPORTANT: the confidence score and hit-rate numbers below are a heuristic
# scoring rubric (points added for margin, odds range, etc.), not a
# statistically validated prediction model. Use it as a filter/ranking tool,
# not as a guarantee.

import os
import threading
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

import requests
import telebot
from flask import Flask, jsonify


# ============================================================
# CONFIG — tune these without touching the logic below
# ============================================================

# The Odds API sport keys to poll. Keep this list SHORT on the free tier —
# each sport key costs `markets_requested x regions_requested` credits per
# call, and the free plan only gives 500 credits/month (~16/day if you poll
# once daily). Full list: https://the-odds-api.com/sports-odds-data/sports-apis.html
# The Odds API sport keys to poll. Keep this list SHORT on the free tier —
# each sport key costs `markets_requested x regions_requested` credits per
# call, and the free plan only gives 500 credits/month (~16/day if you poll
# once daily). Full list: https://the-odds-api.com/sports-odds-data/sports-apis.html
#
# NOTE: EPL / La Liga / Bundesliga / Serie A / Champions League are all on
# their summer break roughly June-August — polling them then will always
# return zero matches, which is expected, not a bug. The list below uses
# leagues/tournaments that run through summer instead.
LEAGUES = [
    {"key": "soccer_fifa_world_cup", "label": "FIFA World Cup 2026"},
    {"key": "soccer_usa_mls", "label": "USA - MLS"},
    {"key": "soccer_brazil_campeonato", "label": "Brazil - Serie A"},
    {"key": "soccer_mexico_ligamx", "label": "Mexico - Liga MX"},
]

REGION = "eu"
MARKETS = "h2h,totals"
ODDS_FORMAT = "decimal"

HIGH_SCORING_KEYWORDS = ["friendly", "friendlies", "u20", "u21", "u19", "youth", "junior"]

MIN_CONFIDENCE = 7
ODDS_1X2_MIN = 1.20
ODDS_1X2_MAX = 2.20
ODDS_O25_MIN = 1.20
ODDS_O25_MAX = 1.80
DRAW_MARGIN_THRESHOLD = 0.10
LEGS_REQUIRED = 4

# Only consider matches kicking off within this many hours from now.
HOURS_WINDOW = 12

ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"


# ============================================================
# ODDS FETCHING — talks to The Odds API
# ============================================================

def fetch_sport_odds(api_key, sport_key):
    """Fetch raw odds for one sport key, restricted to the next HOURS_WINDOW hours."""
    url = f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds"
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=HOURS_WINDOW)

    resp = requests.get(
        url,
        params={
            "apiKey": api_key,
            "regions": REGION,
            "markets": MARKETS,
            "oddsFormat": ODDS_FORMAT,
            # The Odds API expects ISO 8601 UTC, no microseconds, e.g. 2024-01-01T15:30:00Z
            "commenceTimeFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commenceTimeTo": window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def extract_prices(event):
    """Pick a bookmaker's h2h and totals(2.5) prices for one event."""
    home = draw = away = over25 = under25 = None
    bookmaker_used = None

    for bm in event.get("bookmakers", []):
        markets = {m["key"]: m for m in bm.get("markets", [])}
        h2h = markets.get("h2h")
        totals = markets.get("totals")

        if h2h and not bookmaker_used:
            outcomes = {o["name"]: o["price"] for o in h2h["outcomes"]}
            home_price = outcomes.get(event["home_team"])
            away_price = outcomes.get(event["away_team"])
            draw_price = outcomes.get("Draw")
            if home_price and away_price and draw_price:
                home, away, draw = home_price, away_price, draw_price
                bookmaker_used = bm.get("title")

        if totals:
            for o in totals["outcomes"]:
                if o["name"] == "Over" and float(o.get("point", -1)) == 2.5:
                    over25 = o["price"]
                if o["name"] == "Under" and float(o.get("point", -1)) == 2.5:
                    under25 = o["price"]

        if home and draw and away and (over25 or under25):
            break

    if not (home and draw and away):
        return None

    return {
        "home_team": event["home_team"],
        "away_team": event["away_team"],
        "commence_time": event.get("commence_time"),
        "bookmaker": bookmaker_used,
        "odds_home": home,
        "odds_draw": draw,
        "odds_away": away,
        "odds_over25": over25,
        "odds_under25": under25,
    }


def is_within_window(match, hours=HOURS_WINDOW):
    """Client-side safety check in case the API's own date filter is ever loose."""
    raw = match.get("commence_time")
    if not raw:
        return True  # if we don't know, don't drop it — let it through
    try:
        kickoff = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    now = datetime.now(timezone.utc)
    return now <= kickoff <= now + timedelta(hours=hours)


def fetch_all_matches(api_key):
    """Fetch and flatten odds across every configured league."""
    results = []
    for league in LEAGUES:
        try:
            events = fetch_sport_odds(api_key, league["key"])
            for event in events:
                prices = extract_prices(event)
                if prices and is_within_window(prices):
                    prices["league_key"] = league["key"]
                    prices["league_label"] = league["label"]
                    results.append(prices)
        except requests.RequestException as err:
            status = getattr(err.response, "status_code", None)
            print(f"[odds] Failed to fetch {league['key']}: {status} {err}")
    return results


# ============================================================
# PARLAY LOGIC — true probabilities, scoring, filtering, ranking
# ============================================================

def true_probabilities(odds_home, odds_draw, odds_away):
    inv_home = 1 / odds_home
    inv_draw = 1 / odds_draw
    inv_away = 1 / odds_away
    total = inv_home + inv_draw + inv_away
    return {
        "home": inv_home / total,
        "draw": inv_draw / total,
        "away": inv_away / total,
        "overround": total,
    }


def is_high_scoring_league(match):
    haystack = f"{match['league_label']} {match['league_key']}".lower()
    return any(kw in haystack for kw in HIGH_SCORING_KEYWORDS)


def score_candidate(match, bet, odds, true_prob, margin_pct, high_scoring, is_clear_pick, market_type):
    confidence = 5
    if is_clear_pick:
        confidence += 2
    if margin_pct < 8:
        confidence += 1
    if market_type == "1X2" and 1.40 <= odds <= 2.20:
        confidence += 1
    if market_type == "O2.5" and odds < 1.50:
        confidence += 1
    if high_scoring:
        confidence += 1
    confidence = min(confidence, 10)

    return {
        "match": match,
        "bet": bet,
        "market_type": market_type,
        "odds": odds,
        "true_prob": true_prob,
        "confidence": confidence,
        "margin_pct": margin_pct,
    }


def evaluate_match(match):
    probs = true_probabilities(match["odds_home"], match["odds_draw"], match["odds_away"])
    margin_pct = (probs["overround"] - 1) * 100
    high_scoring = is_high_scoring_league(match)

    candidates = []
    home_clear = probs["home"] >= probs["draw"] + DRAW_MARGIN_THRESHOLD
    away_clear = probs["away"] >= probs["draw"] + DRAW_MARGIN_THRESHOLD

    if home_clear:
        candidates.append(score_candidate(match, "Home Win", match["odds_home"], probs["home"],
                                           margin_pct, high_scoring, True, "1X2"))
    if away_clear:
        candidates.append(score_candidate(match, "Away Win", match["odds_away"], probs["away"],
                                           margin_pct, high_scoring, True, "1X2"))

    if match.get("odds_over25") and (high_scoring or not candidates):
        if match.get("odds_under25"):
            inv_over = 1 / match["odds_over25"]
            inv_under = 1 / match["odds_under25"]
            total_ou = inv_over + inv_under
            true_prob_over = inv_over / total_ou
            candidates.append(score_candidate(match, "Over 2.5 Goals", match["odds_over25"], true_prob_over,
                                               margin_pct, high_scoring, high_scoring, "O2.5"))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates[0]


def filter_and_rank(candidates):
    def passes(c):
        if c["confidence"] < MIN_CONFIDENCE:
            return False
        if c["market_type"] == "1X2":
            return ODDS_1X2_MIN <= c["odds"] <= ODDS_1X2_MAX
        if c["market_type"] == "O2.5":
            return ODDS_O25_MIN <= c["odds"] <= ODDS_O25_MAX
        return False

    filtered = [c for c in candidates if passes(c)]
    filtered.sort(key=lambda c: c["confidence"], reverse=True)
    return filtered


def build_parlay_summary(legs):
    combined_odds = 1
    for leg in legs:
        combined_odds *= leg["odds"]
    avg_confidence = sum(leg["confidence"] for leg in legs) / len(legs)
    hit_rate = 50 + (avg_confidence - 1) * 5
    return_pct = (combined_odds - 1) * 100
    return {
        "combined_odds": combined_odds,
        "avg_confidence": avg_confidence,
        "hit_rate": hit_rate,
        "return_pct": return_pct,
    }


def build_parlay(matches):
    evaluated = [c for c in (evaluate_match(m) for m in matches) if c is not None]
    ranked = filter_and_rank(evaluated)

    if len(ranked) < LEGS_REQUIRED:
        return {
            "ok": False,
            "reason": f"Only {len(ranked)} qualifying leg(s) found (need {LEGS_REQUIRED}).",
            "matches_scanned": len(matches),
            "qualifying_legs": ranked,
        }

    legs = ranked[:LEGS_REQUIRED]
    summary = build_parlay_summary(legs)
    return {
        "ok": True,
        "legs": legs,
        "summary": summary,
        "matches_scanned": len(matches),
        "total_qualifying": len(ranked),
    }


# ============================================================
# MESSAGE FORMATTING — builds the exact Telegram output layout
# ============================================================

def reason_for(leg):
    pct = f"{leg['true_prob'] * 100:.1f}"
    if leg["market_type"] == "O2.5":
        return f"High-scoring/friendly profile with {pct}% true probability of Over 2.5 goals."
    side = "home side" if leg["bet"] == "Home Win" else "away side"
    return f"The {side} is priced well above its {pct}% true win probability, clearing the draw by a wide margin."


def format_kickoff(commence_time):
    if not commence_time:
        return "TBD"
    try:
        dt = datetime.strptime(commence_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "TBD"
    return dt.strftime("%a %H:%M UTC")


def format_leg(leg, index):
    m = leg["match"]
    pct = f"{leg['true_prob'] * 100:.1f}"
    lines = [
        f"Leg {index + 1}: {m['home_team']} vs {m['away_team']}",
        f"  🕒 Kickoff: {format_kickoff(m.get('commence_time'))}",
        f"  📊 Bet: {leg['bet']}",
        f"  📈 Odds: {leg['odds']:.2f}",
        f"  🎯 Confidence: {leg['confidence']}/10",
        f"  📊 True Prob: {pct}%",
        f"  📝 Reason: {reason_for(leg)}",
    ]
    return "\n".join(lines)


def format_parlay_message(result):
    if not result["ok"]:
        qualifying = len(result["qualifying_legs"])
        return (
            "⚠️ Not enough qualifying legs today.\n\n"
            f"Scanned {result['matches_scanned']} match(es), found {qualifying} that "
            "cleared the confidence/odds filters (need 4).\n"
            "Try again later, or widen the LEAGUES list near the top of main.py."
        )

    legs = result["legs"]
    summary = result["summary"]
    leg_lines = "\n\n".join(format_leg(leg, i) for i, leg in enumerate(legs))
    count_1x2 = sum(1 for l in legs if l["market_type"] == "1X2")
    count_o25 = sum(1 for l in legs if l["market_type"] == "O2.5")

    lines = [
        "🎯 LOW RISK 4-LEG PARLAY",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        leg_lines,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Combined Odds: {summary['combined_odds']:.2f}",
        f"🎯 Hit Rate: {summary['hit_rate']:.0f}%",
        "💰 Stake: 5% of bankroll",
        f"📈 Return: {summary['return_pct']:.1f}%",
        "",
        "⚠️ Risk: 🟢 LOW",
        "",
        f"📋 Summary: {result['matches_scanned']} matches → 4 selected | "
        f"Avg Conf: {summary['avg_confidence']:.1f}/10 | {count_1x2} x 1X2, {count_o25} x O2.5",
    ]
    return "\n".join(lines)


# ============================================================
# TELEGRAM BOT + WEB SERVER
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")
PORT = int(os.environ.get("PORT", 3000))

if not TELEGRAM_TOKEN:
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN in environment. Set it and restart.")
if not ODDS_API_KEY:
    raise SystemExit("Missing ODDS_API_KEY in environment. Set it and restart.")

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=True)


def run_parlay(chat_id):
    bot.send_message(chat_id, "🔎 Scanning today's odds, one sec...")
    try:
        matches = fetch_all_matches(ODDS_API_KEY)

        if not matches:
            bot.send_message(
                chat_id,
                "No matches with usable odds were returned right now. This can happen between "
                "fixture windows, or if today's slate is thin — try again later, or add more "
                "leagues in the LEAGUES list near the top of main.py.",
            )
            return

        result = build_parlay(matches)
        message = format_parlay_message(result)
        bot.send_message(chat_id, message)

    except Exception as err:  # noqa: BLE001 - top-level guard so the bot never silently dies
        status = getattr(getattr(err, "response", None), "status_code", None)
        if status == 401:
            bot.send_message(chat_id, "❌ The odds API key looks invalid. Check ODDS_API_KEY.")
        elif status == 429:
            bot.send_message(chat_id, "❌ Odds API rate limit hit. Free tier is 500 requests/month — try again later.")
        else:
            print(f"[run_parlay] {err}")
            bot.send_message(chat_id, "❌ Something went wrong pulling odds. Check the server logs.")


@bot.message_handler(commands=["start"])
def handle_start(message):
    bot.send_message(
        message.chat.id,
        "👋 I build a low-risk 4-leg parlay from live soccer odds.\n\n"
        "Send /parlay to scan today's matches and get a pick.\n\n"
        "⚠️ This is a rules-based scoring tool, not a guaranteed predictor. Bet responsibly.",
    )


@bot.message_handler(commands=["parlay"])
def handle_parlay(message):
    threading.Thread(target=run_parlay, args=(message.chat.id,), daemon=True).start()


app = Flask(__name__)


@app.get("/")
def index():
    return "Telegram odds parlay bot is running."


@app.get("/health")
def health():
    return jsonify(ok=True)


def start_bot_polling():
    print("Telegram bot is polling for messages...")
    bot.infinity_polling()


if __name__ == "__main__":
    threading.Thread(target=start_bot_polling, daemon=True).start()
    print(f"Health server listening on port {PORT}")
    app.run(host="0.0.0.0", port=PORT)

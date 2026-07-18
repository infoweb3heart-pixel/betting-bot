# Betting Picks Telegram Bot

An interactive Telegram bot with a button menu. Message it `/start`, tap
**Top Recommendations** or **Parlay Suggestions**, and it scans matches
kicking off in the next N hours (default 12, counted from the moment you
tap the button) and runs them through a 1X2 → Double Chance → Over/Under
decision waterfall.

Deploys as a **free Render Web Service** using a Telegram webhook (not a
paid Background Worker) -- see "Why webhook, not polling" below.

## Files
- `betting_framework.py` — decision engine (probabilities, edge, confidence, decision tree) + `build_parlays()` for combining independent picks into multi-bets
- `league_config.json` — league baselines/multipliers, editable without touching code
- `odds_client.py` — fetches odds from The Odds API, normalizes them, auto-discovers all active soccer leagues, and caches results
- `bot.py` — message formatting helpers
- `main.py` — the bot: `/start` menu, button callbacks, auto-switches between webhook (on Render) and long polling (local dev)
- `render.yaml` — Render **Web Service** deployment config (free tier)

## Why webhook, not polling
Render's Background Worker service type has no free tier (billed compute,
~$7/month+). Render's Web Service type *does* have a free tier, but only
responds to incoming HTTP requests -- it can't run an infinite polling loop
in the background for free. A Telegram **webhook** solves this: Telegram
pushes each update to your service's URL as an HTTP request, which is exactly
what a free Web Service is built to handle.

The tradeoff: Render's free Web Service spins down after 15 minutes with no
traffic, and takes roughly 30-60 seconds to wake up on the next request. So
the first tap after a period of inactivity may feel slow or even time out --
Telegram will retry the webhook delivery, so it should eventually go through,
but responsiveness after idle periods won't be instant. If that's a dealbreaker,
the fix is a small paid Render instance (or another always-on host) instead.

`main.py` auto-detects which mode to use:
- **Locally**: no `RENDER_EXTERNAL_URL` env var is set → runs long polling (simpler for testing, no public URL needed).
- **On Render**: Render injects `RENDER_EXTERNAL_URL` automatically for Web Services → runs webhook mode, binding to Render's `PORT` and registering `https://<your-service>.onrender.com/<TELEGRAM_TOKEN>` as the webhook URL.

## How it works
1. `/start` (or `/menu`) shows two buttons.
2. **Top Recommendations** → fetches matches in the next `WINDOW_HOURS`, evaluates each with `BettingFramework`, filters out `SKIP` and anything below `MIN_CONFIDENCE`, shows the top `MAX_RESULTS` sorted by confidence.
3. **Parlay Suggestions** → same picks, deduplicated to one leg per match (correlated legs from the same match are never combined), combined into a Safe Double, Balanced Treble, and Value Play via `build_parlays()`.
4. Every result screen has a "🔙 Menu" button to go back.

## Local setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and fill in:
   - `TELEGRAM_TOKEN` — from @BotFather
   - `ODDS_API_KEY` — from The Odds API
3. Run it (no `RENDER_EXTERNAL_URL` set, so it runs in polling mode):
   ```bash
   set -a && source .env && set +a
   python main.py
   ```
4. Message your bot `/start` in Telegram and try both buttons before deploying.

## Deploy to Render (free)
1. Push this repo to GitHub.
2. On Render: New → **Web Service** → connect the repo (picks up `render.yaml` automatically, including `plan: free`).
3. Add `TELEGRAM_TOKEN` and `ODDS_API_KEY` as environment variables in the Render dashboard — never commit them.
4. Deploy. Render assigns a URL like `https://betting-telegram-bot.onrender.com` and sets `RENDER_EXTERNAL_URL` for you automatically -- no manual webhook setup needed, `main.py` handles registering it with Telegram on startup.
5. Check the Logs tab for `Running in webhook mode: https://...`.
6. Message the bot on Telegram — first message after a cold start may take up to a minute.

## Tuning
- `SPORT_KEYS` — comma-separated Odds API sport keys to scan (e.g. `soccer_epl,soccer_brazil_campeonato`), or set to `all` to auto-discover and scan every currently active soccer league via `/sports`.
  - **Quota warning**: The Odds API bills per league request. Scanning `all` leagues means one request per active league every time the 5-minute odds cache expires (see `ODDS_CACHE_TTL_SECONDS` in `odds_client.py`). There are often 40-60+ active soccer leagues at once, so this can burn a free-tier plan (e.g. 500 requests/month) in a single scan cycle. Fine for testing or a paid plan; for the free tier, stick to a short explicit league list.
- `WINDOW_HOURS` — how far ahead to look for kickoffs (default 12).
- `MIN_CONFIDENCE` — raise to only surface higher-conviction picks.
- `MAX_RESULTS` — cap on how many single picks show in Top Recommendations.
- `WEBHOOK_SECRET` (optional) — set this to a random string and Render will pass it to Telegram as a shared secret, so your webhook endpoint rejects requests that don't include it.
- `odds_client.py` uses each match's *first* bookmaker only — consider averaging across books or picking a specific preferred one for sharper pricing.
- The Odds API's totals market often only returns a 2.5 goals line; Under/Over 3.5 handling is a placeholder until you confirm your plan returns that line.
- `build_parlays()`'s combined odds assume leg independence, which holds for different matches but can still move together if they're correlated (same league, same day, etc.) — the bot notes this in the parlay message.
- The 60/40 blend of market odds with historical league baselines in `calculate_true_probabilities` is the core assumption in this model — it's only as good as how rigorously those baselines were backtested out-of-sample. Treat outputs as decision support, not guaranteed edges.

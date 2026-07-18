"""
Minimal Telegram send wrapper. Uses the raw Bot API over HTTP so there's no
heavyweight framework dependency for a one-way "push picks" bot.
"""

import os
import requests
from typing import Optional

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.environ.get("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            raise ValueError("Set TELEGRAM_TOKEN and TELEGRAM_CHAT_ID as environment variables.")

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        url = TELEGRAM_API.format(token=self.token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            print(f"Telegram send failed: {resp.status_code} {resp.text}")
            return False
        return True


def format_recommendation(match: dict, decision: dict, index: Optional[int] = None) -> str:
    """Turn one match + decision dict into a readable Telegram message block."""
    home = match["home_team"]
    away = match["away_team"]
    league = match.get("league_name", "")
    prefix = f"{index}. " if index is not None else ""

    lines = [
        f"{prefix}*{home} vs {away}*",
        f"_{league}_",
        f"Pick: *{decision['outcome']}* ({decision['bet_type']}) @ {decision['recommended_odds']}",
        f"Confidence: {decision['confidence']}% | Edge: {decision['edge']:.1%}",
    ]
    return "\n".join(lines)


def format_parlay(parlay: dict, index: int) -> str:
    """Turn one parlay dict (from betting_framework.build_parlays) into a message block."""
    risk_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(parlay["risk"], "")
    lines = [f"{index}. *{parlay['label']}* {risk_emoji}"]
    for leg in parlay["legs"]:
        m, d = leg["match"], leg["decision"]
        lines.append(f"   • {m['home_team']} vs {m['away_team']} — {d['outcome']} @ {d['recommended_odds']}")
    lines.append(f"   Combined odds: *{parlay['combined_odds']}* | Avg confidence: {parlay['avg_confidence']}%")
    return "\n".join(lines)

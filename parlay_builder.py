from typing import Dict, List

from config import CONFIDENCE_THRESHOLD, MAX_PARLAY_LEGS, BANKROLL_STAKE_PCT


class ParlayBuilder:
    def build_parlay(self, analyzed_matches: List[Dict]) -> List[Dict]:
        qualified = [m for m in analyzed_matches if m["confidence"] >= CONFIDENCE_THRESHOLD]
        return qualified[:MAX_PARLAY_LEGS]

    def format_message(self, parlay: List[Dict], total_analyzed: int) -> str:
        if not parlay:
            return (
                "No legs met the confidence threshold today.\n"
                "Try /matches to see everything available, or check back later."
            )

        lines = ["LOW RISK PARLAY", "-" * 28, ""]
        combined_odds = 1.0

        for i, leg in enumerate(parlay, 1):
            combined_odds *= leg["pick_odds"]
            est_tag = " (estimated line)" if leg.get("estimated") else ""
            lines.append(f"Leg {i}: {leg['home_team']} vs {leg['away_team']} ({leg['league']})")
            lines.append(f"  Bet: {leg['bet_type']}{est_tag}")
            lines.append(f"  Odds: {leg['pick_odds']:.2f}")
            lines.append(f"  Confidence: {leg['confidence']}/10")
            lines.append(f"  {leg['probability_label']}: {leg['probability']*100:.1f}%")
            lines.append(f"  Reason: {leg['reason']}")
            lines.append("")

        avg_confidence = sum(leg["confidence"] for leg in parlay) / len(parlay)
        hit_rate = 50 + (avg_confidence - 1) * 5
        x12_count = sum(1 for leg in parlay if leg["bet_type"] != "Over 2.5")
        over_count = len(parlay) - x12_count

        lines.append("-" * 28)
        lines.append(f"Combined Odds: {combined_odds:.2f}")
        lines.append(f"Estimated Hit Rate: {hit_rate:.0f}%")
        lines.append(f"Suggested Stake: {BANKROLL_STAKE_PCT}% of bankroll")
        lines.append(f"Potential Return: {(combined_odds - 1) * BANKROLL_STAKE_PCT:.1f}% of bankroll")
        lines.append("")
        lines.append("Risk Level: LOW")
        lines.append("Bet responsibly. Past performance does not guarantee future results.")
        lines.append("")
        lines.append("Summary:")
        lines.append(f"- {total_analyzed} matches analyzed")
        lines.append(f"- {len(parlay)} selected for parlay")
        lines.append(f"- Average confidence: {avg_confidence:.1f}/10")
        lines.append(f"- Bet types: {x12_count} x 1X2, {over_count} x Over 2.5")

        return "\n".join(lines)

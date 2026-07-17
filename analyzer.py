from typing import Dict, List, Optional, Tuple

from classification import classify_match
from config import (
    MIN_ODDS, MAX_ODDS,
    OVER25_MIN_ODDS, OVER25_MAX_ODDS, OVER25_LOW_ODDS_BONUS_THRESHOLD,
    DRAW_GAP_THRESHOLD, LOW_MARGIN_THRESHOLD, MISMATCH_ODDS_THRESHOLD,
)

# Used only when no bookmaker publishes a totals market for a match, so a
# Friendly/Youth match can still be considered for Over 2.5. This is an
# ESTIMATE, not a market price -- flagged as such in the reason text and in
# the parlay output, and never used to inflate confidence past what real
# odds would justify (see OVER25_LOW_ODDS_BONUS_THRESHOLD check).
ESTIMATED_OVER25_FAIR_ODDS = {
    "friendly_or_youth": 1.35,   # ~74% implied
    "high_scoring": 1.55,        # ~65% implied
    "cup": 1.70,                 # ~59% implied
}


class MatchAnalyzer:
    """For each match: compute true (de-vig) probabilities, evaluate Home
    Win / Away Win / Over 2.5 Goals, score confidence for whichever are
    eligible, and keep whichever bet is strongest for that match."""

    def analyze_matches(self, matches: List[Dict]) -> List[Dict]:
        analyzed = []
        for match in matches:
            leg = self._analyze_one(match)
            if leg is not None:
                analyzed.append(leg)

        analyzed.sort(key=lambda m: m["confidence"], reverse=True)
        return analyzed

    # ------------------------------------------------------------------

    def _analyze_one(self, match: Dict) -> Optional[Dict]:
        odds = match["odds"]
        totals = match.get("totals", {})
        classification = classify_match(
            match.get("league_key", ""), match["league"], match["home_team"], match["away_team"]
        )

        true_probs, margin = self._implied_probabilities(odds)
        favorite_odds = min(odds["home"], odds["away"])

        x12_option = self._evaluate_1x2(odds, true_probs, margin, classification)
        over_option = self._evaluate_over25(totals, classification, favorite_odds)

        # Step 5: use whichever is stronger. Ties favor 1X2 (real market
        # data over an estimate, when both hit the same score).
        if over_option and x12_option:
            chosen = over_option if over_option["confidence"] > x12_option["confidence"] else x12_option
        else:
            chosen = over_option or x12_option

        if chosen is None:
            return None  # Option D: skip

        return {**match, **chosen}

    # ------------------------------------------------------------------
    # True probabilities (de-vig)
    # ------------------------------------------------------------------

    @staticmethod
    def _implied_probabilities(odds: Dict) -> Tuple[Dict, float]:
        home_i = 1 / odds["home"]
        draw_i = 1 / odds["draw"]
        away_i = 1 / odds["away"]
        total = home_i + draw_i + away_i

        true_probs = {"home": home_i / total, "draw": draw_i / total, "away": away_i / total}
        margin = total - 1
        return true_probs, margin

    # ------------------------------------------------------------------
    # Option A/B: Home Win / Away Win
    # ------------------------------------------------------------------

    def _evaluate_1x2(self, odds: Dict, true_probs: Dict, margin: float, classification: Dict) -> Optional[Dict]:
        candidates = []
        if true_probs["home"] >= true_probs["draw"] + DRAW_GAP_THRESHOLD and MIN_ODDS <= odds["home"] <= MAX_ODDS:
            candidates.append(("home", "Home Win"))
        if true_probs["away"] >= true_probs["draw"] + DRAW_GAP_THRESHOLD and MIN_ODDS <= odds["away"] <= MAX_ODDS:
            candidates.append(("away", "Away Win"))

        if not candidates:
            return None

        side, label = max(candidates, key=lambda c: true_probs[c[0]])
        price = odds[side]
        gap = true_probs[side] - true_probs["draw"]

        confidence = 5
        confidence += 2  # clear 1X2 winner (the gap condition above already guarantees this)
        if margin < LOW_MARGIN_THRESHOLD:
            confidence += 1
        if 1.40 <= price <= 2.20:
            confidence += 1
        if classification["is_high_scoring_league"]:
            confidence += 1
        if classification["is_youth"]:
            confidence += 1
        if classification["is_friendly"]:
            confidence += 1
        confidence = min(confidence, 10)

        margin_label = "low" if margin < LOW_MARGIN_THRESHOLD else ("moderate" if margin < 0.12 else "high")
        reason = (
            f"{label.replace(' Win', '')} has {true_probs[side]*100:.1f}% true win probability "
            f"(gap to Draw: {gap*100:.1f}pp). Bookmaker margin is {margin*100:.1f}% ({margin_label}). "
            f"Confidence {confidence}/10."
        )

        return {
            "bet_type": label,
            "pick_odds": price,
            "confidence": confidence,
            "probability": true_probs[side],
            "probability_label": "True Prob",
            "reason": reason,
            "estimated": False,
        }

    # ------------------------------------------------------------------
    # Option C: Over 2.5 Goals
    # ------------------------------------------------------------------

    def _evaluate_over25(self, totals: Dict, classification: Dict, favorite_odds: float) -> Optional[Dict]:
        over_odds = totals.get("over_2_5")
        is_mismatch = favorite_odds < MISMATCH_ODDS_THRESHOLD

        eligible = (
            classification["is_friendly"]
            or classification["is_youth"]
            or classification["is_cup"]
            or classification["is_high_scoring_league"]
            or classification["is_womens"]
            or is_mismatch
            or (over_odds is not None and over_odds < 1.70)
        )
        if not eligible:
            return None

        estimated = over_odds is None
        if estimated:
            if classification["is_friendly"] or classification["is_youth"] or classification["is_womens"]:
                over_odds = ESTIMATED_OVER25_FAIR_ODDS["friendly_or_youth"]
            elif classification["is_high_scoring_league"]:
                over_odds = ESTIMATED_OVER25_FAIR_ODDS["high_scoring"]
            elif classification["is_cup"]:
                over_odds = ESTIMATED_OVER25_FAIR_ODDS["cup"]
            else:
                # Only a mismatch triggered eligibility but there's no real
                # market and no category to estimate from -- too speculative.
                return None

        if not (OVER25_MIN_ODDS <= over_odds <= OVER25_MAX_ODDS):
            return None

        goal_prob = 1 / over_odds

        confidence = 5
        if classification["is_friendly"] or classification["is_youth"] or classification["is_womens"]:
            confidence += 2
        if classification["is_high_scoring_league"]:
            confidence += 1
        if not estimated and over_odds < OVER25_LOW_ODDS_BONUS_THRESHOLD:
            confidence += 1
        if is_mismatch:
            confidence += 1
        if classification["is_cup"]:
            confidence += 1
        confidence = min(confidence, 10)

        match_type_bits = [k.replace("is_", "").replace("_", " ") for k, v in classification.items() if v]
        match_type_label = "/".join(match_type_bits) if match_type_bits else "standard"

        odds_note = f"Bookmaker Over 2.5 odds: {over_odds:.2f}." if not estimated else \
            f"No published Over 2.5 line -- estimated fair odds {over_odds:.2f} from match type."

        reason = (
            f"{match_type_label.title()} match. Goal probability ~{goal_prob*100:.0f}%. {odds_note} "
            f"Confidence {confidence}/10."
        )

        return {
            "bet_type": "Over 2.5",
            "pick_odds": over_odds,
            "confidence": confidence,
            "probability": goal_prob,
            "probability_label": "Goal Prob",
            "reason": reason,
            "estimated": estimated,
        }

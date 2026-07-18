"""
COMPLETE BETTING DECISION FRAMEWORK - BACKTESTED VERSION
1X2 -> Double Chance -> Over/Under -> Skip

Loads league parameters from league_config.json instead of hardcoding them,
so tuning the model doesn't require touching code.
"""

import json
import os
from typing import Dict, List, Optional

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "league_config.json")


class BettingFramework:
    def __init__(self, league_type: str = "normal", league_name: str = "",
                 config_path: str = CONFIG_PATH):
        self.league_type = league_type
        self.league_name = league_name

        with open(config_path, "r") as f:
            self.config = json.load(f)

        self.min_edge = self.config.get("min_edge", 0.03)
        self.weights = self.config["confidence_weights"]
        self.league_params = self._get_league_parameters(league_type, league_name)

    # ---------------------------------------------------------------
    # League parameter resolution
    # ---------------------------------------------------------------
    def _get_league_parameters(self, league_type: str, league_name: str) -> Dict:
        base = self.config["league_parameters"]
        params = base.get(league_type, base["normal"]).copy()

        if league_name:
            params = self._apply_league_specific_tuning(params, league_name)

        return params

    def classify_league(self, league_name: str) -> str:
        """Look up a league's type from the classification lists in config."""
        name_lower = league_name.lower()
        classification = self.config.get("league_classification", {})
        for league_type, names in classification.items():
            if any(n.lower() in name_lower for n in names):
                return league_type
        return "normal"

    def _apply_league_specific_tuning(self, params: Dict, league_name: str) -> Dict:
        league_lower = league_name.lower()

        if any(x in league_lower for x in ["brasil", "argentina", "uruguay", "mexico", "liga mx"]):
            params["under_2.5_baseline"] = min(0.65, params["under_2.5_baseline"] + 0.05)
            params["min_under_2.5_odds"] = max(1.70, params["min_under_2.5_odds"] - 0.05)
            params["conf_multiplier_ou"] = min(1.30, params["conf_multiplier_ou"] + 0.05)

        if "a-league" in league_lower:
            params["under_2.5_baseline"] = max(0.42, params["under_2.5_baseline"] - 0.05)
            params["min_under_3.5_odds"] = max(1.70, params["min_under_3.5_odds"] + 0.10)

        if "premier" in league_lower or "epl" in league_lower:
            params["under_2.5_baseline"] = 0.50
            params["conf_multiplier_1x2"] = 1.20

        if "new zealand" in league_lower or "national league" in league_lower:
            params["conf_multiplier_1x2"] = 1.25

        if "srl" in league_lower or "simulated" in league_lower:
            params["under_2.5_baseline"] = 0.60
            params["conf_multiplier_ou"] = 1.25

        return params

    # ---------------------------------------------------------------
    # Step 1: odds extraction
    # ---------------------------------------------------------------
    def extract_odds(self, home_odds: float, draw_odds: float, away_odds: float,
                      over_odds: float = None, under_odds: float = None,
                      over_35_odds: float = None, under_35_odds: float = None,
                      dc_1x: float = None, dc_x2: float = None, dc_12: float = None) -> Dict:
        return {
            "1": home_odds,
            "X": draw_odds,
            "2": away_odds,
            "over": over_odds,
            "under": under_odds,
            "over_3.5": over_35_odds,
            "under_3.5": under_35_odds,
            "dc_1x": dc_1x,
            "dc_x2": dc_x2,
            "dc_12": dc_12,
        }

    # ---------------------------------------------------------------
    # Step 2: true probabilities
    # ---------------------------------------------------------------
    def calculate_true_probabilities(self, odds: Dict) -> Dict:
        implied = {
            "1": 100 / odds["1"],
            "X": 100 / odds["X"],
            "2": 100 / odds["2"],
        }
        overround = sum(implied.values()) / 100

        true_probs = {
            "1": implied["1"] / overround,
            "X": implied["X"] / overround,
            "2": implied["2"] / overround,
        }

        if odds.get("dc_1x"):
            true_probs["dc_1x"] = true_probs["1"] + true_probs["X"]
            true_probs["dc_x2"] = true_probs["X"] + true_probs["2"]
            true_probs["dc_12"] = true_probs["1"] + true_probs["2"]

        if odds.get("under") and odds.get("over"):
            implied_under = 100 / odds["under"]
            implied_over = 100 / odds["over"]
            ou_overround = (implied_under + implied_over) / 100

            baseline_under = self.league_params["under_2.5_baseline"] * 100
            baseline_over = self.league_params["over_2.5_baseline"] * 100

            true_probs["under"] = (implied_under / ou_overround) * 0.6 + baseline_under * 0.4
            true_probs["over"] = (implied_over / ou_overround) * 0.6 + baseline_over * 0.4

        if odds.get("under_3.5") and odds.get("over_3.5"):
            implied_under35 = 100 / odds["under_3.5"]
            implied_over35 = 100 / odds["over_3.5"]
            ou35_overround = (implied_under35 + implied_over35) / 100

            baseline_under35 = self.league_params["under_3.5_baseline"] * 100

            true_probs["under_3.5"] = (implied_under35 / ou35_overround) * 0.6 + baseline_under35 * 0.4
            true_probs["over_3.5"] = 100 - true_probs["under_3.5"]

        return {"true_probs": true_probs, "overround": overround}

    # ---------------------------------------------------------------
    # Step 3: decision tree
    # ---------------------------------------------------------------
    def decision_tree(self, probs: Dict, odds: Dict) -> Dict:
        decision = {
            "level": None,
            "bet_type": None,
            "outcome": None,
            "confidence": 0,
            "edge": 0,
            "recommended_odds": None,
            "reasoning": [],
        }

        max_prob = max(probs["true_probs"]["1"], probs["true_probs"]["X"], probs["true_probs"]["2"])
        max_outcome = max(("1", "X", "2"), key=lambda k: probs["true_probs"][k])

        threshold = 55 if self.league_params["goal_variance"] in ["high", "very_high"] else 50

        if max_prob > threshold:
            decision.update({
                "level": "1X2",
                "bet_type": "1X2",
                "outcome": max_outcome,
                "recommended_odds": odds[max_outcome],
                "confidence": self._calculate_confidence(probs, odds, max_outcome),
                "edge": self._calculate_edge(probs, odds, max_outcome),
            })
            decision["reasoning"].append(f"{max_outcome} has {max_prob:.1f}% probability (> {threshold}%)")
            return decision

        decision["reasoning"].append(f"1X2 unclear (max {max_prob:.1f}%) -> checking DC")

        if odds.get("dc_1x"):
            dc_options = {
                "1X": {"prob": probs["true_probs"]["dc_1x"], "odds": odds["dc_1x"]},
                "X2": {"prob": probs["true_probs"]["dc_x2"], "odds": odds["dc_x2"]},
                "12": {"prob": probs["true_probs"]["dc_12"], "odds": odds["dc_12"]},
            }

            best_dc, best_edge = None, -999
            for outcome, data in dc_options.items():
                edge = self._calculate_edge_from_prob(data["prob"], data["odds"])
                if edge > best_edge:
                    best_edge, best_dc = edge, outcome

            if best_edge > self.min_edge:
                decision.update({
                    "level": "Double Chance",
                    "bet_type": "DC",
                    "outcome": best_dc,
                    "recommended_odds": dc_options[best_dc]["odds"],
                    "confidence": self._calculate_confidence_dc(dc_options, best_dc),
                    "edge": best_edge,
                })
                decision["reasoning"].append(f"DC {best_dc} has {best_edge:.1%} edge")
                return decision

        decision["reasoning"].append("No DC value -> checking O/U")

        if self.league_params["goal_variance"] in ["high", "very_high"] and odds.get("under_3.5"):
            under35_edge = self._calculate_edge_from_prob(
                probs["true_probs"].get("under_3.5", self.league_params["under_3.5_baseline"] * 100),
                odds["under_3.5"],
            )
            if (under35_edge > self.min_edge and
                    odds["under_3.5"] >= self.league_params["min_under_3.5_odds"]):
                decision.update({
                    "level": "Over/Under",
                    "bet_type": "O/U",
                    "outcome": "Under 3.5",
                    "recommended_odds": odds["under_3.5"],
                    "confidence": self._calculate_confidence_ou(probs, odds, "under_3.5", "Under 3.5"),
                    "edge": under35_edge,
                })
                decision["reasoning"].append(f"Under 3.5 has {under35_edge:.1%} edge in {self.league_type} league")
                return decision

        if odds.get("under") and odds.get("over"):
            under_edge = self._calculate_edge_from_prob(probs["true_probs"]["under"], odds["under"])
            if (under_edge > self.min_edge and
                    odds["under"] >= self.league_params["min_under_2.5_odds"]):
                decision.update({
                    "level": "Over/Under",
                    "bet_type": "O/U",
                    "outcome": "Under 2.5",
                    "recommended_odds": odds["under"],
                    "confidence": self._calculate_confidence_ou(probs, odds, "under", "Under 2.5"),
                    "edge": under_edge,
                })
                decision["reasoning"].append(f"Under 2.5 has {under_edge:.1%} edge")
                return decision

            over_edge = self._calculate_edge_from_prob(probs["true_probs"]["over"], odds["over"])
            if (over_edge > self.min_edge and
                    odds["over"] >= self.league_params["min_over_2.5_odds"]):
                decision.update({
                    "level": "Over/Under",
                    "bet_type": "O/U",
                    "outcome": "Over 2.5",
                    "recommended_odds": odds["over"],
                    "confidence": self._calculate_confidence_ou(probs, odds, "over", "Over 2.5"),
                    "edge": over_edge,
                })
                decision["reasoning"].append(f"Over 2.5 has {over_edge:.1%} edge")
                return decision

        decision.update({
            "level": "SKIP",
            "bet_type": "None",
            "outcome": "No value found",
            "confidence": 0,
            "edge": 0,
        })
        decision["reasoning"].append("No clear value in 1X2, DC, or O/U -> SKIP")
        return decision

    # ---------------------------------------------------------------
    # Edge / confidence helpers
    # ---------------------------------------------------------------
    def _calculate_edge(self, probs: Dict, odds: Dict, outcome: str) -> float:
        true_prob = probs["true_probs"][outcome]
        implied_prob = 100 / odds[outcome]
        return (true_prob - implied_prob) / 100

    def _calculate_edge_from_prob(self, true_prob: float, odds: float) -> float:
        implied_prob = 100 / odds
        return (true_prob - implied_prob) / 100

    def _calculate_confidence(self, probs: Dict, odds: Dict, outcome: str) -> int:
        score = 0

        prob = probs["true_probs"][outcome]
        prob_margin = min(1, max(0, (prob - 50) / 40))
        score += prob_margin * self.weights["prob_margin"] * 100

        edge = self._calculate_edge(probs, odds, outcome)
        edge_mult = self.league_params.get("edge_multiplier_1x2", 1.0)
        edge_score = min(1, max(0, (edge + 0.20) / 0.40))
        score += edge_score * self.weights["edge_size"] * 100 * edge_mult

        overround_score = max(0, 1 - (probs["overround"] - 1) * 2)
        score += overround_score * self.weights["overround"] * 100

        conf_mult = self.league_params.get("conf_multiplier_1x2", 1.0)
        league_score = min(1, conf_mult * 0.8)
        score += league_score * self.weights["league_reliability"] * 100

        variance_penalty = {"low": 0, "normal": 0, "high": -5, "very_high": -10}.get(
            self.league_params.get("goal_variance", "normal"), 0
        )
        score += variance_penalty * self.weights["goal_variance"]

        return int(min(100, max(0, score)))

    def _calculate_confidence_dc(self, dc_options: Dict, chosen: str) -> int:
        base = 55
        edge = self._calculate_edge_from_prob(dc_options[chosen]["prob"], dc_options[chosen]["odds"])
        bonus = min(20, max(0, edge * 100 * 0.5))

        variance_penalty = {"low": 0, "normal": 0, "high": -5, "very_high": -10}.get(
            self.league_params.get("goal_variance", "normal"), 0
        )

        return int(min(100, max(0, base + bonus + variance_penalty)))

    def _calculate_confidence_ou(self, probs: Dict, odds: Dict, outcome: str, bet_name: str) -> int:
        if "3.5" in bet_name:
            base = 65 if self.league_params["goal_variance"] in ["high", "very_high"] else 55
        else:
            base = 55

        edge = self._calculate_edge_from_prob(probs["true_probs"][outcome], odds[outcome])
        edge_mult = self.league_params.get("edge_multiplier_ou", 1.0)
        bonus = min(25, max(0, edge * 100 * 0.6 * edge_mult))

        conf_mult = self.league_params.get("conf_multiplier_ou", 1.0)
        league_bonus = (conf_mult - 1.0) * 25

        variance_adj = {"low": 5, "normal": 0, "high": -5, "very_high": -10}.get(
            self.league_params.get("goal_variance", "normal"), 0
        )

        return int(min(100, max(0, base + bonus + league_bonus + variance_adj)))

    # ---------------------------------------------------------------
    # Reporting helpers
    # ---------------------------------------------------------------
    def top_recommendations(self, decisions: List[Dict], n: int = 3) -> List[Dict]:
        valid = [d for d in decisions if d["level"] != "SKIP"]
        return sorted(valid, key=lambda x: x["confidence"], reverse=True)[:n]

    def evaluate_match(self, home_odds, draw_odds, away_odds, **kwargs) -> Dict:
        """Convenience wrapper: run the full pipeline for one match's odds."""
        odds = self.extract_odds(home_odds, draw_odds, away_odds, **kwargs)
        probs = self.calculate_true_probabilities(odds)
        return self.decision_tree(probs, odds)


def build_parlays(picks: List[Dict], max_legs: int = 3) -> List[Dict]:
    """
    Build parlay suggestions from a list of single-match picks.

    picks: list of {"match": <match dict>, "decision": <decision dict>},
    already filtered to non-SKIP decisions, one entry per match (don't pass
    two legs from the same match together -- that's correlated, not independent).

    Returns a list of parlay dicts: {label, legs, combined_odds, avg_confidence, risk}.
    Combined odds assume leg independence (true for different matches), which is
    the standard simplification for pre-match multi-bets -- it is NOT a guarantee,
    just the product of the individual prices.
    """
    if not picks:
        return []

    ranked = sorted(picks, key=lambda p: p["decision"]["confidence"], reverse=True)
    parlays = []

    def make_parlay(label: str, legs: List[Dict], risk: str) -> Dict:
        combined_odds = 1.0
        confidences = []
        for leg in legs:
            combined_odds *= leg["decision"]["recommended_odds"]
            confidences.append(leg["decision"]["confidence"])
        return {
            "label": label,
            "legs": legs,
            "combined_odds": round(combined_odds, 2),
            "avg_confidence": int(sum(confidences) / len(confidences)),
            "risk": risk,
        }

    if len(ranked) >= 2:
        parlays.append(make_parlay("Safe Double", ranked[:2], "low"))

    if len(ranked) >= 3:
        parlays.append(make_parlay("Balanced Treble", ranked[:3], "medium"))

    by_edge = sorted(picks, key=lambda p: p["decision"]["edge"], reverse=True)
    value_legs = by_edge[:max_legs]
    if len(value_legs) >= 2:
        parlays.append(make_parlay("Value Play", value_legs, "high"))

    return parlays

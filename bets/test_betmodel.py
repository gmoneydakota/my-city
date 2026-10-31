#!/usr/bin/env python3
"""Offline tests for the odds math, distributions, ratings fit and Underdog entries.

    python3 test_betmodel.py
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from betmodel import common, engine, props, ratings  # noqa: E402


class OddsMath(unittest.TestCase):
    def test_conversions(self):
        self.assertAlmostEqual(common.american_to_decimal(-110), 1.9090909, 6)
        self.assertAlmostEqual(common.american_to_decimal(150), 2.5)
        self.assertEqual(common.decimal_to_american(2.5), 150)
        self.assertEqual(common.decimal_to_american(1.5), -200)
        self.assertEqual(common.parse_american("+142"), 142)
        self.assertEqual(common.parse_american("EVEN"), 100)
        self.assertIsNone(common.parse_american("OFF"))
        self.assertIsNone(common.parse_american(None))

    def test_devig(self):
        a, b = common.devig_two_way(-110, -110)
        self.assertAlmostEqual(a, 0.5, 6)
        a, b = common.devig_two_way(-300, 240)
        self.assertAlmostEqual(a + b, 1, 9)
        self.assertGreater(a, 0.72)
        # power method gives the favourite a bit more than proportional normalisation
        pa, pb = common.implied_prob(-300), common.implied_prob(240)
        self.assertGreater(a, pa / (pa + pb))

    def test_ev_kelly(self):
        self.assertAlmostEqual(common.expected_value(0.5, 100), 0.0)
        self.assertGreater(common.expected_value(0.55, -110), 0)
        self.assertEqual(common.kelly_fraction(0.4, -110), 0.0)
        self.assertLessEqual(common.kelly_fraction(0.9, 100), 0.02)


class Distributions(unittest.TestCase):
    def test_normal_half_line(self):
        o, u, p = common.prob_over_under(20.5, 20.5, 5, discrete=False)
        self.assertAlmostEqual(o, 0.5, 6)
        self.assertEqual(p, 0.0)

    def test_integer_line_push(self):
        o, u, p = common.prob_over_under(3, 3.0, 1.8, discrete=True)
        self.assertGreater(p, 0.1)
        self.assertAlmostEqual(o + u + p, 1, 6)

    def test_negbin_mean(self):
        pmf = common.negbin_pmf_list(2.5, 4.0, 80)
        self.assertAlmostEqual(sum(pmf), 1, 6)
        self.assertAlmostEqual(sum(k * x for k, x in enumerate(pmf)), 2.5, 3)

    def test_model_shrink(self):
        proj = {"mean": 30, "sd": 5, "discrete": False}
        o, u, _ = props.model_probs(proj, 20.5)
        raw = common.prob_over_under(20.5, 30, 5, False)[0]
        self.assertLess(o, raw)
        self.assertGreater(o, 0.5)


class Ratings(unittest.TestCase):
    def test_recovers_strength(self):
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        strength = {"A": 6, "B": 0, "C": -6}
        games, i = [], 0
        for rnd in range(30):
            for h, a in [("A", "B"), ("B", "C"), ("C", "A"), ("B", "A"), ("C", "B"), ("A", "C")]:
                i += 1
                games.append({"event_id": str(i), "date": t0 + timedelta(days=i), "home": h, "away": a,
                              "home_score": 110 + strength[h] + 1.5, "away_score": 110 + strength[a] - 1.5,
                              "final": True, "neutral": False})
        asof = games[-1]["date"] + timedelta(days=2)
        m = ratings.TeamModel("nba").fit(games, asof)
        p = m.predict("A", "C", asof)  # true margin: 12 + 3 home edge, minus ridge shrinkage
        self.assertAlmostEqual(m.hca, 3.0, 0)
        self.assertGreater(p["margin"], 10)
        self.assertGreater(p["p_home"], 0.75)


class Underdog(unittest.TestCase):
    def test_breakeven(self):
        self.assertAlmostEqual(engine.ud_breakeven(2), 0.57735, 4)
        self.assertAlmostEqual(engine.ud_breakeven(3), 0.55032, 4)

    def test_entries_respect_breakeven_and_correlation(self):
        legs = [dict(athlete_id=str(k), stat="points", event_id="g1" if k < 3 else f"g{k}", p=0.6, value=0.6,
                     player=f"P{k}", side="over", line=10.5) for k in range(6)]
        ents = engine.best_entries(legs)
        self.assertTrue(ents)
        for e in ents:
            self.assertGreater(e["ev"], 0)
            games = [l["event_id"] for l in e["legs"]]
            self.assertLessEqual(max(games.count(g) for g in games), 2)
        self.assertEqual(engine.best_entries([dict(legs[0], value=0.52, p=0.52)]), [])


class Stats(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(props.canon_stat("nba", "Pts+Rebs+Asts"), "pra")
        self.assertEqual(props.canon_stat("nfl", "Receiving Yards"), "rec_yds")
        self.assertIsNone(props.canon_stat("nba", "fantasy points"))


if __name__ == "__main__":
    unittest.main(verbosity=1)

import unittest

import pandas as pd

from src.elo import backtest, brier_score


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.matches = pd.DataFrame(
            [
                ("match:1", "2026-01-01", "team:alpha", "team:bravo", 2, 0, 1),
                ("match:2", "2026-01-01", "team:alpha", "team:charlie", 2, 0, 1),
                ("match:3", "2026-01-02", "team:alpha", "team:charlie", 2, 0, 1),
            ],
            columns=[
                "match_id",
                "date",
                "team_a_id",
                "team_b_id",
                "score_a",
                "score_b",
                "is_lan",
            ],
        )

    def test_same_day_predictions_use_only_prior_days(self):
        _, predictions = backtest(self.matches)
        by_match = predictions.set_index("match_id")

        self.assertEqual(by_match.loc["match:1", "p_a"], 0.5)
        self.assertEqual(by_match.loc["match:2", "p_a"], 0.5)
        self.assertGreater(by_match.loc["match:3", "p_a"], 0.5)

    def test_same_day_input_order_does_not_change_ratings(self):
        ratings, _ = backtest(self.matches)
        reversed_ratings, _ = backtest(self.matches.iloc[::-1])

        for team_id, rating in ratings.items():
            self.assertAlmostEqual(rating, reversed_ratings[team_id])

    def test_brier_score(self):
        predictions = pd.DataFrame({"p_a": [0.8, 0.4], "a_won": [1, 0]})

        self.assertAlmostEqual(brier_score(predictions), 0.1)

    def test_empty_database_query_shape_returns_no_ratings(self):
        empty = self.matches.iloc[0:0]
        ratings, predictions = backtest(empty)

        self.assertEqual(ratings, {})
        self.assertTrue(predictions.empty)


if __name__ == "__main__":
    unittest.main()

import pandas as pd


START_ELO = 1500
K = 32
LAN_WEIGHT = 1.0
ONLINE_WEIGHT = 0.6
MARGIN_BONUS = 0.2
DECAY_HALF_LIFE = 180


def expected(rating_a, rating_b):
    return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))


def backtest(matches):
    matches = matches.copy()
    matches["date"] = pd.to_datetime(matches["date"])
    ratings, last_seen, history = {}, {}, []

    for match_date, day in matches.sort_values("date").groupby("date", sort=True):
        teams = set(day["team_a_id"]) | set(day["team_b_id"])
        for team_id in teams:
            ratings.setdefault(team_id, START_ELO)
            if team_id in last_seen:
                inactive_days = (match_date - last_seen[team_id]).days
                ratings[team_id] = START_ELO + (ratings[team_id] - START_ELO) * (
                    0.5 ** (inactive_days / DECAY_HALF_LIFE)
                )

        updates = []
        for match in day.itertuples():
            probability_a = expected(
                ratings[match.team_a_id], ratings[match.team_b_id]
            )
            a_won = int(match.score_a > match.score_b)
            margin = abs(match.score_a - match.score_b)
            weight = LAN_WEIGHT if match.is_lan else ONLINE_WEIGHT
            k = K * weight * (1 + MARGIN_BONUS * (margin - 1))
            delta = k * (a_won - probability_a)

            history.append(
                {
                    "match_id": match.match_id,
                    "date": match_date,
                    "p_a": probability_a,
                    "a_won": a_won,
                }
            )
            updates.append((match.team_a_id, match.team_b_id, delta))

        for team_a_id, team_b_id, delta in updates:
            ratings[team_a_id] += delta
            ratings[team_b_id] -= delta
        for team_id in teams:
            last_seen[team_id] = match_date

    return ratings, pd.DataFrame(history)


def brier_score(predictions):
    return ((predictions.p_a - predictions.a_won) ** 2).mean()

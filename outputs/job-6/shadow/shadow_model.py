"""Shadow module: only the changes that won the walk-forward tests in outputs/job-6/REPORT.md.

Pure functions, no network, no file writes. Needs numpy + scipy only for the ridge/distribution part.
Feature flag: set env LUCKY_SHADOW=1 (see INTEGRATE.md). Never changes live picks by itself.

1. market_weight(league, bet_type)  -> how much weight the market gets (NFL ML/spread/total: ~1.0)
2. nfl_ml_prob(spread_line, sigma)  -> NFL home-win prob from the closing spread (beat de-vigged ML in test)
3. NflPassModel / RidgeDist         -> ridge mean + fitted-variance gamma/neg-binomial over probabilities
4. nba_ml_prob(p_model, p_elo, rest_h, rest_a, coef) -> NBA team-rating + rest logistic blend
5. shrink_to_market(p_model, p_market, w) and confidence_floor(...)
"""
import math
import os

ENABLED = os.environ.get("LUCKY_SHADOW", "0") == "1"

# Weight on OUR model (rest goes to the market). From results/games_metrics.json:
# NFL moneyline: market 0.608 log loss vs current model 0.646, 50/50-ish blend 0.6145 -> market wins.
# NFL spread/total: any model weight made log loss worse than the 0.693 coin-flip at the line.
MODEL_WEIGHT = {("nfl", "ml"): 0.0, ("nfl", "spread"): 0.0, ("nfl", "total"): 0.0,
                ("nba", "ml"): 1.0,  # no NBA market history cached, so the NBA result is model-vs-model only
                ("nba", "spread"): 0.5, ("nba", "total"): 0.5}
# Floor on the calibrated probability a pick needs before it can be shown (backtest-based; see REPORT)
CONF_FLOOR = {"nfl_ml": 0.55, "nfl_spread": 0.55, "nfl_total": 0.55, "nfl_pass_prop": 0.58, "nfl_rush_rec_prop": 0.60,
              "nba_ml": 0.57}


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigm(x):
    return 1 / (1 + math.exp(-x))


def market_weight(league, bet_type):
    return MODEL_WEIGHT.get((league, bet_type), 0.0)


def nfl_ml_prob(spread_line, sigma=13.5):
    """spread_line: nflverse convention, positive = home favoured by that many points."""
    return ncdf(spread_line / sigma)


def shrink_to_market(p_model, p_market, w):
    """Blend in logit space. w = weight on the model (0..1)."""
    return sigm(w * logit(p_model) + (1 - w) * logit(p_market))


def nba_ml_prob(p_model, p_elo, rest_h, rest_a, coef=None):
    """Logistic blend of team-rating prob, elo prob and rest. Refit coef with fit_nba_blend() on your own history."""
    c = coef or {"b": 0.0, "model": 0.6, "elo": 0.4, "rest_diff": 0.02, "b2b_h": -0.10, "b2b_a": 0.10}
    z = (c["b"] + c["model"] * logit(p_model) + c["elo"] * logit(p_elo) + c["rest_diff"] * (rest_h - rest_a)
         + c["b2b_h"] * float(rest_h < 1.5) + c["b2b_a"] * float(rest_a < 1.5))
    return sigm(z)


def fit_nba_blend(rows):
    """rows: dicts with p_model, p_elo, rest_h, rest_a, y (home won). Returns coef dict for nba_ml_prob."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    X = np.array([[logit(r["p_model"]), logit(r["p_elo"]), r["rest_h"] - r["rest_a"], float(r["rest_h"] < 1.5),
                   float(r["rest_a"] < 1.5)] for r in rows])
    m = LogisticRegression(C=1.0).fit(X, [r["y"] for r in rows])
    k = m.coef_[0]
    return {"b": float(m.intercept_[0]), "model": float(k[0]), "elo": float(k[1]), "rest_diff": float(k[2]),
            "b2b_h": float(k[3]), "b2b_a": float(k[4])}


class RidgeDist:
    """Ridge mean + variance = a*mu^b (fitted on training residuals) -> P(over line) via gamma (yards) or neg-binomial (counts)."""
    FEATS = ["ew3", "ew6", "ew20", "last3", "n_prior", "implied", "home", "opp_rel"]

    def __init__(self, is_count, alpha=10.0):
        self.is_count, self.alpha = is_count, alpha

    def fit(self, X, y):
        import numpy as np
        from sklearn.linear_model import Ridge
        X, y = np.asarray(X, float), np.asarray(y, float)
        self.fill = np.nanmean(X, axis=0)
        X = np.where(np.isnan(X), self.fill, X)
        self.rg = Ridge(alpha=self.alpha).fit(X, y)
        mu = np.maximum(self.rg.predict(X), 0.3)
        r2 = (y - mu) ** 2
        edges = np.quantile(mu, np.linspace(0, 1, 11))
        idx = np.clip(np.searchsorted(edges, mu, side="right") - 1, 0, 9)
        gm = np.array([mu[idx == i].mean() for i in range(10) if (idx == i).any()])
        gr = np.array([r2[idx == i].mean() for i in range(10) if (idx == i).any()])
        b = float(np.clip(np.polyfit(np.log(gm), np.log(gr), 1)[0], 0.8, 2.0))
        self.b = b
        self.a = math.exp(float(np.mean(np.log(gr)) - b * np.mean(np.log(gm))))
        return self

    def predict(self, X):
        import numpy as np
        X = np.asarray(X, float)
        X = np.where(np.isnan(X), self.fill, X)
        return np.maximum(self.rg.predict(X), 0.3)

    def p_over(self, X, line):
        import numpy as np
        from scipy import stats as st
        mu = self.predict(X)
        var = self.a * mu ** self.b
        line = np.asarray(line, float)
        if self.is_count:
            var = np.maximum(var, mu * 1.02)
            r = mu * mu / (var - mu)
            p = r / (r + mu)
            return 1 - st.nbinom.cdf(np.ceil(line).astype(int) - 1, r, p)
        return st.gamma.sf(line, mu * mu / var, scale=var / mu)


def pick_ok(category, p_calibrated):
    return p_calibrated >= CONF_FLOOR.get(category, 0.60)


if __name__ == "__main__":
    import random
    random.seed(7)
    print("enabled:", ENABLED)
    print("nfl_ml_prob(-3 home underdog => spread_line=-3):", round(nfl_ml_prob(-3), 3))
    print("shrink:", round(shrink_to_market(0.70, 0.55, 0.0), 3), round(shrink_to_market(0.70, 0.55, 0.5), 3))
    try:
        import numpy as np
        rs = np.random.RandomState(7)
        X = rs.normal(250, 40, (400, 8))
        y = X[:, 1] + rs.normal(0, 55, 400)
        m = RidgeDist(False).fit(X, y)
        print("p_over 250.5 at mean 250:", np.round(m.p_over(X[:3], [250.5] * 3), 3))
    except ImportError:
        print("numpy/scipy/sklearn missing: ridge part skipped")

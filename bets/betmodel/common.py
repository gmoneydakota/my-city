"""Shared helpers: cached HTTP, odds math and probability distributions.

Standard library only, so the model runs anywhere Python 3.9+ is installed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache"
UA = "Mozilla/5.0 (X11; Linux x86_64) AgentCity-BetModel/1.0"


class DataError(RuntimeError):
    pass


# --------------------------------------------------------------------------- HTTP
def get_json(url: str, params: dict | None = None, ttl_hours: float = 6.0,
             headers: dict | None = None, cache: bool = True):
    """GET a JSON document, caching the body on disk for ``ttl_hours``.

    The cache filename is a SHA-1 of the URL, so API keys are never written to disk.
    """
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    path = CACHE_DIR / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if cache and ttl_hours > 0 and path.exists() and time.time() - path.stat().st_mtime < ttl_hours * 3600:
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass  # corrupt cache entry: refetch
    last = None
    for attempt in range(3):
        try:
            h = {"User-Agent": UA, "Accept": "application/json"}
            h.update(headers or {})
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
                body = r.read()
            data = json.loads(body)
            if cache and ttl_hours > 0:
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_bytes(body)
            return data
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404, 422):  # not retryable
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
        time.sleep(1.5 * (attempt + 1))
    safe = url.split("apiKey=")[0]
    raise DataError(f"GET failed: {safe} ({last})")


def prune_cache(max_age_days: float = 3.0) -> None:
    """Delete cached responses older than max_age_days (game logs add up fast)."""
    if not CACHE_DIR.exists():
        return
    cutoff = time.time() - max_age_days * 86400
    for p in CACHE_DIR.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------- odds
def american_to_decimal(a: float) -> float:
    a = float(a)
    if a == 0:
        raise ValueError("American odds cannot be 0")
    return 1 + (a / 100 if a > 0 else 100 / -a)


def decimal_to_american(d: float) -> int:
    if d <= 1:
        raise ValueError("decimal odds must be > 1")
    return round((d - 1) * 100) if d >= 2 else round(-100 / (d - 1))


def implied_prob(american: float) -> float:
    return 1 / american_to_decimal(american)


def prob_to_american(p: float) -> int:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return decimal_to_american(1 / p)


def parse_american(x) -> float | None:
    """'+142' / '-110' / 'EVEN' / 142 -> float, or None if missing/unparseable."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x) if x else None
    s = str(x).strip().upper()
    if s in ("EVEN", "EV", "PK"):
        return 100.0
    try:
        v = float(s.replace("+", ""))
        return v if abs(v) >= 100 else None
    except ValueError:
        return None


def devig_two_way(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Remove the vig from a two-way market with the power method.

    Finds k with pa**k + pb**k = 1. Unlike simple normalising, this assigns more of
    the margin to the longshot, which matches favourite-longshot bias in practice.
    """
    pa, pb = implied_prob(odds_a), implied_prob(odds_b)
    if pa + pb <= 1:  # no vig (or arb): just normalise
        s = pa + pb
        return pa / s, pb / s
    lo, hi = 1.0, 10.0
    for _ in range(60):
        k = (lo + hi) / 2
        if pa ** k + pb ** k > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    fa, fb = pa ** k, pb ** k
    s = fa + fb
    return fa / s, fb / s


def expected_value(p: float, american: float) -> float:
    """Expected profit per 1 unit staked."""
    return p * american_to_decimal(american) - 1


def kelly_fraction(p: float, american: float, fraction: float = 0.25, cap: float = 0.02) -> float:
    """Fractional Kelly stake as a share of bankroll, capped (default 1/4 Kelly, max 2%)."""
    b = american_to_decimal(american) - 1
    f = (b * p - (1 - p)) / b
    return max(0.0, min(cap, f * fraction))


# --------------------------------------------------------------------------- distributions
def norm_cdf(x: float, mu: float = 0.0, sd: float = 1.0) -> float:
    return 0.5 * (1 + math.erf((x - mu) / (sd * math.sqrt(2))))


def poisson_pmf_list(mu: float, kmax: int) -> list[float]:
    out = [math.exp(-mu)]
    for k in range(1, kmax + 1):
        out.append(out[-1] * mu / k)
    return out


def negbin_pmf_list(mu: float, var: float, kmax: int) -> list[float]:
    """Negative binomial pmf (mean mu, variance var > mu); falls back to Poisson."""
    if var <= mu * 1.0001:
        return poisson_pmf_list(mu, kmax)
    r = mu * mu / (var - mu)
    p = r / (r + mu)  # success prob
    out = [p ** r]
    for k in range(1, kmax + 1):
        out.append(out[-1] * (k - 1 + r) / k * (1 - p))
    return out


def prob_over_under(line: float, mu: float, sd: float, discrete: bool) -> tuple[float, float, float]:
    """Return (P(over), P(under), P(push)) for a stat with mean mu and sd.

    discrete=True uses a negative binomial (good for low counts: threes, receptions,
    TDs, rebounds); otherwise a normal with continuity correction (points, yards).
    """
    mu = max(mu, 0.01)
    sd = max(sd, 0.5)
    integer_line = abs(line - round(line)) < 1e-9
    if discrete:
        kmax = int(mu + 12 * sd + 20)
        pmf = negbin_pmf_list(mu, sd * sd, kmax)
        tot = sum(pmf)
        pmf = [x / tot for x in pmf]
        under = sum(p for k, p in enumerate(pmf) if k < line - 1e-9)
        push = pmf[int(round(line))] if integer_line and 0 <= round(line) <= kmax else 0.0
        over = max(0.0, 1 - under - push)
        return over, under, push
    if integer_line:
        under = norm_cdf(line - 0.5, mu, sd)
        over = 1 - norm_cdf(line + 0.5, mu, sd)
        return over, under, 1 - over - under
    over = 1 - norm_cdf(line, mu, sd)
    return over, 1 - over, 0.0


def weighted_mean_sd(values: list[float], weights: list[float]) -> tuple[float, float, float]:
    """Weighted mean, weighted sd, and effective sample size."""
    sw = sum(weights)
    if not values or sw <= 0:
        return 0.0, 0.0, 0.0
    m = sum(v * w for v, w in zip(values, weights)) / sw
    var = sum(w * (v - m) ** 2 for v, w in zip(values, weights)) / sw
    n_eff = sw * sw / sum(w * w for w in weights)
    if n_eff > 1.5:
        var *= n_eff / (n_eff - 1)  # small-sample correction
    return m, math.sqrt(max(var, 0.0)), n_eff


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v else default

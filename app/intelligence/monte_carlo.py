from __future__ import annotations

import math
import random
from collections import Counter
from typing import Any


def _poisson(lam: float, rng: random.Random) -> int:
    threshold = math.exp(-max(0.01, lam))
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= rng.random()
    return count - 1


def simulate(home_xg: float, away_xg: float, iterations: int = 20000, seed: int | None = None) -> dict[str, Any]:
    iterations = max(1000, min(int(iterations), 100000))
    rng = random.Random(seed if seed is not None else round(home_xg * 10000 + away_xg * 1000))
    outcomes = Counter(); scores = Counter(); totals = Counter(); btts = 0
    for _ in range(iterations):
        h, a = _poisson(home_xg, rng), _poisson(away_xg, rng)
        scores[(h, a)] += 1
        outcomes['HOME_WIN' if h > a else 'AWAY_WIN' if a > h else 'DRAW'] += 1
        totals['OVER_1_5'] += h + a >= 2
        totals['OVER_2_5'] += h + a >= 3
        totals['OVER_3_5'] += h + a >= 4
        btts += h > 0 and a > 0
    probs = {k: round(outcomes[k] / iterations, 4) for k in ('HOME_WIN','DRAW','AWAY_WIN')}
    markets = {**probs,
        'OVER_1_5': round(totals['OVER_1_5']/iterations,4),
        'OVER_2_5': round(totals['OVER_2_5']/iterations,4),
        'OVER_3_5': round(totals['OVER_3_5']/iterations,4),
        'BTTS_YES': round(btts/iterations,4)}
    top_scores=[{'score':f'{h}-{a}','probability':round(n/iterations,4)} for (h,a),n in scores.most_common(8)]
    # Approximate 95% Monte Carlo sampling interval for each 1X2 probability.
    intervals={}
    for key,p in probs.items():
        se=math.sqrt(max(p*(1-p),0)/iterations)
        intervals[key]={'low':round(max(0,p-1.96*se),4),'high':round(min(1,p+1.96*se),4)}
    return {'iterations':iterations,'markets':markets,'top_scores':top_scores,'intervals':intervals}

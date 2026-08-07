from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


def calibration_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("result") not in {"WIN", "LOSS"} or row.get("probability") is None:
            continue
        bucket = min(9, int(float(row["probability"])*10))
        buckets[bucket].append(row)
    out = []
    for bucket in sorted(buckets):
        items = buckets[bucket]
        predicted = sum(float(x["probability"]) for x in items)/len(items)
        actual = sum(x["result"] == "WIN" for x in items)/len(items)
        out.append({"range": f"{bucket*10}-{bucket*10+9}%", "samples": len(items), "predicted": round(predicted*100,1), "actual": round(actual*100,1)})
    return out


def professional_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled = [x for x in rows if x.get("result") in {"WIN", "LOSS"}]
    if not settled:
        return {"samples": 0, "accuracy": 0, "brier": None, "log_loss": None, "calibration": []}
    accuracy = sum(x["result"] == "WIN" for x in settled)/len(settled)
    brier = sum((float(x.get("probability") or .5) - (1 if x["result"] == "WIN" else 0))**2 for x in settled)/len(settled)
    logloss = -sum((1 if x["result"] == "WIN" else 0)*math.log(max(.001,float(x.get("probability") or .5))) + (0 if x["result"] == "WIN" else 1)*math.log(max(.001,1-float(x.get("probability") or .5))) for x in settled)/len(settled)
    return {"samples": len(settled), "accuracy": round(accuracy*100,1), "brier": round(brier,4), "log_loss": round(logloss,4), "calibration": calibration_summary(settled)}

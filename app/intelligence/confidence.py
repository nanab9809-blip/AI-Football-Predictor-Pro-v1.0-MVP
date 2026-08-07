from __future__ import annotations
from typing import Any


def dynamic(base: float, *, data_quality: float, agreement: float, league_reliability: float=55.0,
            market_reliability: float=55.0, odds_available: bool=False, lineups_available: bool=False,
            drift_points: float=0.0) -> dict[str, Any]:
    adjustments=[]
    def add(label: str, value: float):
        adjustments.append({'label':label,'value':round(value,1)})
    add('Data quality',(data_quality-65)*.16)
    add('Model agreement',(agreement-65)*.14)
    add('League reliability',(league_reliability-55)*.10)
    add('Market reliability',(market_reliability-55)*.10)
    add('Bookmaker odds available',2.0 if odds_available else -2.0)
    add('Official line-ups',3.0 if lineups_available else -3.0)
    add('Prediction drift',-min(10,abs(drift_points)*.45))
    final=max(15,min(95,float(base)+sum(x['value'] for x in adjustments)))
    return {'base':round(float(base),1),'final':round(final,1),'adjustments':adjustments,
            'status':'HIGH' if final>=78 else 'MEDIUM' if final>=62 else 'LOW'}

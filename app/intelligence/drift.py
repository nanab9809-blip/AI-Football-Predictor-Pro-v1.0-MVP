from __future__ import annotations
from typing import Any


def compare(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if len(snapshots)<2:
        return {'available':False,'max_drift':0.0,'status':'BASELINE','events':[]}
    events=[]; max_drift=0.0
    prev=snapshots[-1]
    for current in reversed(snapshots[:-1]):
        drift=abs(float(current.get('probability') or 0)-float(prev.get('probability') or 0))*100
        max_drift=max(max_drift,drift)
        events.append({'from':prev.get('created_at'),'to':current.get('created_at'),'drift':round(drift,1),
                       'probability':round(float(current.get('probability') or 0)*100,1)})
        prev=current
    return {'available':True,'max_drift':round(max_drift,1),'status':'ALERT' if max_drift>=10 else 'WATCH' if max_drift>=5 else 'STABLE','events':events}

from __future__ import annotations
from typing import Any


def _shrink(wins: int, total: int, prior: float=.55, strength: int=40) -> float:
    return (wins + prior*strength)/(total+strength) if total+strength else prior


def summarize(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups={'league':{},'market':{},'league_market':{}}
    for r in rows:
        if r.get('result') not in ('WIN','LOSS'): continue
        win=1 if r['result']=='WIN' else 0
        vals={'league':r.get('league') or 'Unknown','market':r.get('market_key') or r.get('pick') or 'Unknown'}
        vals['league_market']=f"{vals['league']} · {vals['market']}"
        for kind,key in vals.items():
            g=groups[kind].setdefault(key,{'name':key,'sample':0,'wins':0,'profit':0.0})
            g['sample']+=1; g['wins']+=win; g['profit']+=float(r.get('profit') or 0)
    out={}
    for kind,items in groups.items():
        data=[]
        for g in items.values():
            raw=g['wins']/g['sample'] if g['sample'] else 0
            adj=_shrink(g['wins'],g['sample'])
            g.update({'accuracy':round(raw*100,1),'reliability':round(adj*100,1),
                      'status':'TRUSTED' if g['sample']>=100 and adj>=.58 else 'MONITOR' if g['sample']>=30 else 'LOW_SAMPLE'})
            data.append(g)
        out[kind]=sorted(data,key=lambda x:(x['reliability'],x['sample']),reverse=True)
    return out

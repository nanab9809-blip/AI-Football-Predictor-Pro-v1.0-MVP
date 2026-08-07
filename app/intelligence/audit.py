from __future__ import annotations
from typing import Any


def build(analysis: dict[str, Any], data_quality: dict[str, Any], dynamic_confidence: dict[str, Any], monte_carlo: dict[str, Any]) -> dict[str, Any]:
    internal=analysis.get('internal',{})
    best=analysis.get('best_pick',{})
    models=internal.get('models',{})
    key=best.get('key') or 'HOME_WIN'
    model_rows=[]
    for name,probs in models.items():
        model_rows.append({'model':name.title(),'probability':round(float(probs.get(key,0))*100,1),
                           'weight':round(float(internal.get('weights',{}).get(name,0))*100,1)})
    contributions=[
      {'factor':'Model ensemble','impact':round((internal.get('model_agreement',50)-50)*.18,1)},
      {'factor':'Home advantage','impact':3.5},
      {'factor':'Recent form gap','impact':round((internal.get('home_features',{}).get('ppg',0)-internal.get('away_features',{}).get('ppg',0))*4,1)},
      {'factor':'Attack/defence balance','impact':round((internal.get('home_features',{}).get('attack_rating',50)-internal.get('away_features',{}).get('defense_rating',50))*.08,1)},
      {'factor':'Data quality','impact':round((data_quality['score']-65)*.08,1)},
    ]
    return {'model_version':'3.0-intelligence','feature_version':'3.0','selected_market':best.get('label'),
            'selected_probability':best.get('probability_pct'),'models':model_rows,'contributions':contributions,
            'quality':data_quality,'confidence':dynamic_confidence,'monte_carlo':monte_carlo,
            'warnings':data_quality.get('warnings',[])}

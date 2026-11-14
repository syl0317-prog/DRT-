"""Auditable congestion analysis. No road-name or node-name spatial matching."""
import numpy as np
import pandas as pd

AS_OF = '2026-11-10'

def summarize(observations):
    rows = []
    for (source, link), f in observations.groupby(['source', 'link_id'], sort=True):
        speeds = pd.to_numeric(f.speed_kmh, errors='coerce')
        times = pd.to_numeric(f.travel_time_sec, errors='coerce')
        valid = (speeds > 0) & (times > 0) & np.isfinite(speeds) & np.isfinite(times)
        s, t = speeds[valid], times[valid]
        lengths = pd.to_numeric(f.length_m, errors='coerce')
        implied = speeds * times / 3.6
        discrepancy = abs(implied-lengths)/lengths
        rows.append(dict(source=source, link_id=link, road_name=f.road_name.iloc[0],
            direction=f.direction.iloc[0], observation_count=len(f), valid_count=int(valid.sum()),
            mean_speed_kmh=s.mean(), mean_travel_time_sec=t.mean(), speed_std=s.std(),
            length_m=lengths.mean(), max_length_time_relative_error=discrepancy.max(),
            observed_at=';'.join(sorted(set(f.observed_at))), as_of=AS_OF,
            quality='timestamp_missing' if (f.observed_at == 'missing').any() else 'single_snapshot',
            reference_speed_kmh=np.nan, speed_reduction_pct=np.nan,
            period_speed_change_pct=np.nan, congestion_time_increase_pct=np.nan,
            invalid_count=int((~valid).sum()), length_consistency='review' if (discrepancy > .1).any() else 'consistent' if lengths.notna().any() else 'missing'))
    out = pd.DataFrame(rows)
    # Relative distribution screen only: cross-sectional, not an absolute congestion diagnosis.
    out['relative_class'] = 'missing'
    out['criterion'] = '출처별 속도 Q25 이하/중앙값 이상; exploratory cross-sectional; road class uncontrolled'
    for source, idx in out.groupby('source').groups.items():
        s = out.loc[idx, 'mean_speed_kmh']
        out.loc[idx, 'source_q25_kmh'] = s.quantile(.25)
        out.loc[idx, 'source_median_kmh'] = s.median()
        out.loc[idx, 'relative_class'] = np.where(s <= s.quantile(.25), 'relatively_slow', np.where(s >= s.median(), 'relatively_smooth', 'middle'))
    return out

def route_audit(cache):
    rows = []
    for key, route in sorted(cache.items()):
        rows.append(dict(route_id=key, osrm_duration_min=route['duration_min'], distance_km=route['distance_km'],
            osrm_retrieved_at=route.get('retrieved_at', 'missing'), source=route.get('source', 'OSRM'),
            observation_count=0, matched_link_count=0, matching_rate=0, observed_distance_fraction=0,
            observed_time_fraction=0, gits_duration_min='missing', fallback_duration_min=route['duration_min'],
            quality='unmatchable', reason='GITS directed geometry / verified OSRM crosswalk missing; OSRM has no GITS IDs or edge times', as_of=AS_OF))
    return pd.DataFrame(rows)

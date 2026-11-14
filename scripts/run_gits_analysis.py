"""Offline, reproducible extension. Does not modify any source or existing results."""
import json
import sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'sewook31'))
from gits_xlsx import read_sheets
from modules.gits_analysis import summarize, route_audit, AS_OF
from modules.strategy_sim import compare
from modules.punctuality_sim import simulate_minutes, calibrate
from modules.settings import setting

OUT = ROOT/'data/processed'
def save(f, name):
    f.to_csv(OUT/name, index=False, encoding='utf-8-sig', na_rep='missing')

def main():
    sheets = read_sheets(OUT/'위례_DRT_GITS_도로교통정보_정리.xlsx')
    raw = sheets['xl/worksheets/sheet4.xml'].iloc[2:]
    x = pd.DataFrame(dict(link_id=raw.B, road_name=raw.A, direction=raw.C+' → '+raw.D,
        speed_kmh=raw.E, travel_time_sec=raw.F, length_m=raw.H,
        observed_at=raw.J.where(raw.J.str.contains(r'^\d{4}-', na=False), 'missing')))
    x['source'] = 'GITS workbook / original observation sheet'
    h = pd.read_csv(ROOT/'data/raw/wirye_traffic_history.csv', encoding='utf-8-sig', dtype={'link_id': str})
    h = h.rename(columns={'axis_dir': 'direction', 'collected_at': 'observed_at'})
    h['source'] = 'wirye_traffic_history.csv; provider lineage unverified'
    h['length_m'] = float('nan')
    obs = pd.concat([x, h], ignore_index=True)
    summary = summarize(obs)
    save(summary, 'gits_link_summary.csv')
    save(summary[['source','link_id','observation_count','valid_count','invalid_count','quality','length_consistency','max_length_time_relative_error','as_of']], 'gits_data_quality.csv')
    profiles = summary[['source','link_id','observation_count','quality','as_of']].merge(pd.DataFrame({'period':['출퇴근','평시']}), how='cross')
    profiles['period_observation_count'] = 0
    profiles['mean_speed_kmh'] = 'missing'
    profiles['mean_travel_time_sec'] = 'missing'
    profiles['reason'] = 'workbook timestamp missing; CSV snapshot 00:37; no period-specific link observations'
    save(profiles, 'gits_time_profiles.csv')
    speed = pd.read_csv(ROOT/'data/raw/wirye_speed_raw.csv', encoding='utf-8-sig')
    hourly = speed.melt(id_vars=['YY','MT','DE','ROUTE_CD','ROUTE_NM','BGPT_LOC','LASTSTOP_LOC','UPNDW_DIV'], value_vars=[f'TM{i:02}_SPEED' for i in range(1,25)], var_name='hour_field', value_name='speed_kmh')
    hourly['quality'] = hourly.speed_kmh.map(lambda v: 'zero_semantics_unverified' if v == 0 else 'segment_only_not_GITS_link')
    hourly['source'] = 'wirye_speed_raw.csv; hour interval semantics and provider need verification'
    hourly['as_of'] = AS_OF
    save(hourly, 'gits_unmatched_hourly_segments.csv')
    cache = json.loads((ROOT/'sewook31/data/osrm_cache.json').read_text(encoding='utf-8'))
    routes = route_audit(cache)
    save(routes, 'gits_route_matching.csv'); save(routes, 'gits_route_travel_times.csv')
    timetable = json.loads((ROOT/'data/assumptions/tram_timetable.json').read_text(encoding='utf-8'))
    results, baselines = [], []
    for period, spec in timetable.items():
        H = spec['headway_minutes']
        results.append(compare(routes, period, H, runs=int(setting('simulation_runs'))))
        for _, r in routes.iterrows():
            miss, wait = simulate_minutes(r.osrm_duration_min, H, 5, 0, calibrate()[0], setting('dwell_minutes'), setting('detour_per_passenger'), setting('simulation_runs'), setting('random_seed'))
            baselines.append(dict(route_id=r.route_id, period=period, baseline_failure_rate=miss, baseline_transfer_wait_min=wait,
                gits_failure_rate='missing', gits_difference='missing', actual_observed_fraction=0,
                runs=setting('simulation_runs'), seed=setting('random_seed'), observation_count=0,
                source='existing punctuality_sim.simulate_minutes; OSRM fallback', quality='gits_blocked', as_of=AS_OF))
    save(pd.DataFrame(baselines), 'punctuality_gits_results.csv')
    comparison = pd.concat(results, ignore_index=True)
    save(comparison, 'drt_strategy_comparison.csv')
    metrics = ['success_rate','failure_rate','call_wait_min','vehicle_travel_min','transfer_wait_min','total_time_min','p95_total_time_min']
    # No pooling of unrelated cached routes: summary remains route/period-specific.
    save(comparison[['route_id','period','strategy','quality','source','as_of','observation_count','runs']+metrics], 'drt_strategy_summary.csv')
    print('links', len(summary), 'observations', len(obs), 'routes', len(routes), 'GITS coverage 0%; C blocked')
    print(comparison.groupby(['period','strategy','quality'], dropna=False).size().to_string())

if __name__ == '__main__':
    main()

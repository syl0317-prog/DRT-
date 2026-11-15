from modules.timetable_periods import load_periods
"""Seeded arrival/departure simulation. Minutes relative to target tram departure 0."""
import json
import math
from statistics import fmean, multimode
import numpy as np
import pandas as pd
from modules.settings import PROJECT_DIR, PARAMS_FILE, load_params, setting, stops_path

FIELDS = ['노선', '정류장', '환승역', '시간대', '여유분', '합승수', '놓칠확률', '평균대기분', '기준대기분', '가정']

def calibrate(persist=False):
    path = PROJECT_DIR / 'data/assumptions/travel_time_observed.csv'
    ratios = []
    if path.exists():
        frame = pd.read_csv(path, encoding='utf-8-sig')
        required = {'실측소요분', 'OSRM소요분', '검증상태', '출처'}
        if required <= set(frame):
            for _, r in frame.iterrows():
                try:
                    observed, osrm = float(r['실측소요분']), float(r['OSRM소요분'])
                    if r['검증상태'] == 'verified' and pd.notna(r['출처']) and str(r['출처']) != 'missing' and math.isfinite(observed) and math.isfinite(osrm) and min(observed, osrm) > 0:
                        ratios.append(observed/osrm)
                except (ValueError, TypeError):
                    continue
    if len(ratios) >= 3:
        low, high = min(ratios), max(ratios)
        modes = multimode(ratios)
        mode = modes[0] if len(modes) == 1 else max(low, min(high, 3*fmean(ratios)-low-high))
        values = (low, mode, high)
        source = f'실측 {len(ratios)}건 반영; 비율 최소/최빈/최대; 유일 표본최빈값이 없으면 삼각분포 적률식 3*평균-최소-최대(범위 제한)'
        status = 'sourced'
    else:
        values = (1.0, 1.2, 1.5)
        source, status = '실측 입력 전 가정값; 검증된 양수 쌍 최소 3건 필요', 'assumption'
    if persist:
        params = load_params()
        for key, value in zip(('k_min', 'k_mode', 'k_max'), values):
            params[key] = {'value': value, 'status': status, 'source': source}
        PARAMS_FILE.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding='utf-8')
    return values, len(ratios), status, source

def arrival_metrics(arrivals, headway):
    """Catch departure 0 if arrival<=0; otherwise next scheduled departure ceil(a/H)*H."""
    arrivals = np.asarray(arrivals, dtype=float)
    departures = np.where(arrivals <= 0, 0, np.ceil(arrivals/headway)*headway)
    return float(np.mean(arrivals > 0)), float(np.mean(departures-arrivals))

def simulate_minutes(T, headway, buffer, shared, k, dwell, detour, runs, seed):
    if not (0 < T and headway > 0 and 0 < k[0] <= k[1] <= k[2] and runs > 0):
        raise ValueError('Invalid simulation inputs')
    rng = np.random.default_rng(seed)
    factors = np.full(runs, k[0]) if k[0] == k[2] else rng.triangular(*k, size=runs)
    # Pickup planned at -(uncongested OSRM + dwell + buffer).
    # Shared detour is a sensitivity scenario not included in that baseline pickup.
    pickup = -(T+dwell+buffer)
    arrivals = pickup + T*factors + dwell + shared*detour
    return arrival_metrics(arrivals, headway)

def generate(k=None, allow_network=False, legs=None):
    """R01~R04 boarding stop → route final destination, same plans as the operating web."""
    calibrated, n, status, source = calibrate()
    k = tuple(k or calibrated)
    assumption = f'{source}; k={k}; 운영 노선 R01~R04 정류장·순서·최종 목적지; 출발=-(차내시간+정차+여유); 합승 추가시간은 예정출발에 미반영; 가상시간표'
    timetable = load_periods()
    if legs is None:
        from modules.punctuality_routes import route_legs
        legs, _problems = route_legs(allow_network=allow_network)
    rows = []
    for leg in legs:
        name = f"{leg['stop_name']} ({leg['stop_id']})"
        for period, spec in timetable.items():
            H = spec['headway_minutes']
            for shared in range(3):
                for b in range(11):
                    if leg['ride_min'] is None:
                        miss, wait = 'missing', 'missing'
                        note = f"계산 불가: 도로 모형 미확인({leg['missing'] or '경로 없음'}); " + assumption
                    else:
                        miss, wait = simulate_minutes(leg['ride_min'], H, b, shared, k,
                            setting('dwell_minutes'), setting('detour_per_passenger'), setting('simulation_runs'), setting('random_seed'))
                        note = assumption + f"; 차내시간={leg['ride_min']:.6f}분({leg['source']}); 환승역={leg['destination_name']}"
                    rows.append(dict(zip(FIELDS, [leg['route_id'], name, leg['destination_name'], period, b, shared, miss, wait, H/2, note])))
    return pd.DataFrame(rows, columns=FIELDS)

def save_results(frame):
    path = PROJECT_DIR / 'data/processed/punctuality_results.csv'
    frame.to_csv(path, index=False, encoding='utf-8-sig')
    return path

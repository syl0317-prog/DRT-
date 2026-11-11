"""Conditional isolated-trip experiment, not a demand/fleet simulation.

Same ready times and traffic draws for A/B. C is blocked until directed
link matching and temporally validated forecasts exist. No invented fleet KPIs.
"""
import numpy as np
import pandas as pd
from modules.punctuality_sim import calibrate, simulate_minutes
from modules.settings import setting
from modules.gits_analysis import AS_OF

def compare(routes, period, headway, buffer=5, shared=0, vehicles=4, runs=10000, seed=None):
    if vehicles < 1 or shared < 0 or runs < 1 or headway <= 0 or buffer < 0:
        raise ValueError('Invalid scenario')
    seed = int(setting('random_seed')) if seed is None else seed
    k, _, _, _ = calibrate()
    rng = np.random.default_rng(seed)
    factors = rng.triangular(*k, size=runs)
    # Assumption: hypothetical requests become ready uniformly in one target headway.
    ready = rng.uniform(-headway, 0, size=runs)
    rows = []
    for _, r in routes.iterrows():
        T = float(r.osrm_duration_min)
        dwell = float(setting('dwell_minutes'))
        detour = shared * float(setting('detour_per_passenger'))
        travel = T*factors + dwell + detour
        for strategy in ('A', 'B', 'C'):
            row = dict(route_id=r.route_id, period=period, strategy=strategy, runs=runs, seed=seed,
                vehicles=vehicles, shared=shared, buffer_min=buffer, capacity=setting('vehicle_capacity'),
                source='OSRM cache + sim_params + virtual timetable; GITS 0%', as_of=AS_OF,
                observation_count=0, quality='assumption_conditional_isolated_trip',
                congestion_factor=str(k), success_rate='missing', failure_rate='missing',
                call_wait_min='missing', vehicle_travel_min='missing', transfer_wait_min='missing',
                total_time_min='missing', p95_total_time_min='missing', fleet_distance_km='missing',
                handled_calls='missing', rejection_rate='missing',
                limitation='vehicle assumed available at pickup; no fleet/reposition dispatch; uniform ready-time assumption; intersection delay missing',
                dispatch_status='missing_fleet_dispatch', gits_fraction=0)
            if strategy == 'C':
                row['quality'] = 'blocked_missing_gits_geometry_and_history'
            elif shared+1 <= setting('vehicle_capacity'):
                # A dispatches immediately to ready passenger without consulting timetable.
                # B schedules pickup backwards, but never before the identical passenger is ready.
                pickup = ready if strategy == 'A' else np.maximum(ready, -(T+dwell+detour+buffer))
                arrival = pickup + travel
                departure = np.maximum(0, np.ceil(arrival/headway)*headway)
                wait = departure-arrival
                total = departure-ready
                row.update(success_rate=float(np.mean(arrival <= 0)), failure_rate=float(np.mean(arrival > 0)),
                    call_wait_min=float(np.mean(pickup-ready)), vehicle_travel_min=float(np.mean(T*factors)),
                    transfer_wait_min=float(np.mean(wait)), total_time_min=float(np.mean(total)),
                    p95_total_time_min=float(np.quantile(total, .95)),
                    pickup_rule='immediate_at_ready' if strategy == 'A' else 'max(ready,target-base-dwell-detour-buffer)',
                    pickup_mean_min=float(np.mean(pickup)), loaded_trip_distance_km=float(r.distance_km))
            else:
                row['quality'] = 'blocked_capacity'
            rows.append(row)
    return pd.DataFrame(rows)

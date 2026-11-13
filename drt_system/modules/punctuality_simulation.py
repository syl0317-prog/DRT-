"""Research-only timing and conditional Monte Carlo probabilities. No dispatch I/O."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from statistics import NormalDist

import numpy as np


def nonnegative(name, value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name}: 유한한 0 이상의 값이 필요합니다.")
    return value


@dataclass(frozen=True)
class DelayModel:
    kind: str = "uniform"
    fixed: float = 5.0
    minimum: float = 0.0
    maximum: float = 10.0
    mean: float = 5.0
    std: float = 2.0


def sample_delays(model, runs=1000, seed=20261113):
    if isinstance(runs, bool) or not isinstance(runs, (int, np.integer)) or not 1 <= runs <= 100000:
        raise ValueError("반복 횟수는 1~100,000 정수여야 합니다.")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("난수 시드는 0 이상의 정수여야 합니다.")
    rng = np.random.default_rng(seed)
    if model.kind == "fixed":
        return np.full(runs, nonnegative("고정 지연", model.fixed))
    low, high = nonnegative("최소 지연", model.minimum), nonnegative("최대 지연", model.maximum)
    if high < low:
        raise ValueError("최대 지연은 최소 지연 이상이어야 합니다.")
    if model.kind == "uniform":
        return rng.uniform(low, high, size=runs)
    if model.kind != "truncated_normal":
        raise ValueError("지원하지 않는 지연 분포입니다.")
    mean, std = nonnegative("절단 전 정규분포 평균", model.mean), nonnegative("표준편차", model.std)
    if std == 0 or high == low:
        raise ValueError("절단 정규분포는 양의 표준편차와 최소<최대가 필요합니다.")
    normal = NormalDist(mean, std)
    left, right = normal.cdf(low), normal.cdf(high)
    if right - left < 1e-12:
        raise ValueError("절단 구간의 확률질량이 너무 작습니다. 평균·표준편차·범위를 조정하세요.")
    probabilities = rng.uniform(left, right, size=runs)
    # Inverse-CDF sampling, not clipping normal draws (which creates point masses).
    delays = np.array([normal.inv_cdf(float(p)) for p in np.clip(probabilities, 1e-16, 1-1e-16)])
    return np.clip(delays, low, high)  # Only floating-point roundoff protection.


def validate_times(departure, target, tram):
    if not all(isinstance(t, datetime) for t in (departure, target, tram)):
        raise ValueError("날짜를 포함한 datetime 입력이 필요합니다.")
    if len({t.utcoffset() is None for t in (departure, target, tram)}) != 1:
        raise ValueError("시각의 시간대 설정을 통일하세요.")
    if target < departure or tram < departure:
        raise ValueError("목표/트램 시각이 출발보다 빠릅니다. 익일이면 날짜를 변경하세요.")


def evaluate_timing(departure, travel_min, target, tram, delay_min=0, tolerance_min=0,
                    walk_min=3, buffer_min=2):
    validate_times(departure, target, tram)
    travel, delay, tolerance, walk, buffer = [nonnegative(n, v) for n, v in (
        ("이동시간", travel_min), ("추가 지연", delay_min), ("정시 허용 오차", tolerance_min),
        ("보행시간", walk_min), ("환승 여유", buffer_min))]
    expected = departure + timedelta(minutes=travel)
    arrival = expected + timedelta(minutes=delay)
    ready = arrival + timedelta(minutes=walk+buffer)
    margin = (tram-ready).total_seconds()/60
    return dict(departure=departure, expected_arrival=expected, delayed_arrival=arrival,
                target=target, tram_departure=tram, ready_at=ready, delay_min=delay,
                on_time=arrival <= target+timedelta(minutes=tolerance),
                target_margin_min=(target-arrival).total_seconds()/60,
                transfer_success=ready <= tram, transfer_margin_min=margin,
                transfer_excess_min=max(0, -margin), walk_and_buffer_min=walk+buffer,
                result_type="research_simulation")


def simulate(departure, base_travel_min, target, tram, model=DelayModel(), runs=1000,
             seed=20261113, general_increase_pct=20, severe_increase_pct=50,
             tolerance_min=0, walk_min=3, buffer_min=2):
    evaluate_timing(departure, base_travel_min, target, tram, tolerance_min=tolerance_min,
                    walk_min=walk_min, buffer_min=buffer_min)
    base = nonnegative("기준 이동시간", base_travel_min)
    general = nonnegative("일반 혼잡 증가율", general_increase_pct)
    severe = nonnegative("심한 혼잡 증가율", severe_increase_pct)
    if severe <= general:
        raise ValueError("심한 혼잡 증가율은 일반 혼잡보다 커야 합니다.")
    delays = sample_delays(model, runs, seed)
    target_offset = (target-departure).total_seconds()/60
    tram_offset = (tram-departure).total_seconds()/60
    summaries, samples = [], {}
    # Common random numbers isolate congestion effects between scenarios.
    for name, pct in (("A — 기본 운행", 0), ("B — 일반 혼잡", general), ("C — 심한 혼잡", severe)):
        travel = base * (1+pct/100)
        arrivals = travel + delays
        on_time = arrivals <= target_offset+tolerance_min
        success = arrivals+walk_min+buffer_min <= tram_offset
        success_pct = float(success.mean()*100)
        summaries.append(dict(scenario=name, increase_pct=pct, travel_min=travel,
                              mean_delay_min=float(delays.mean()),
                              mean_elapsed_min=float(arrivals.mean()),
                              mean_extra_vs_base_min=float((arrivals-base).mean()),
                              mean_target_lateness_min=float(np.maximum(arrivals-target_offset, 0).mean()),
                              on_time_pct=float(on_time.mean()*100), transfer_success_pct=success_pct,
                              transfer_failure_pct=100-success_pct, runs=runs,
                              result_type="research_simulation"))
        samples[name] = dict(delay_min=delays.copy(), arrival_offset_min=arrivals,
                             on_time=on_time, transfer_success=success)
    return dict(summary=summaries, samples=samples, seed=seed, model=model,
                policy="Probabilities conditional on assumed delay distribution and congestion; not observed.")

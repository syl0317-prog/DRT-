"""Documented congestion factor per route and peak period.

Priority (highest first):
1. Field observations: >= MIN_OBSERVED verified trips for the same route and period in
   data/assumptions/travel_time_observed.csv -> ratio observed / model minutes,
   triangular(min, mode, max) with the same mode rule as punctuality_sim.calibrate.
2. Route composition from data/processed/route_link_matching.csv (MOCT link matching):
   * arterial links (ROAD_RANK 101~103, same class as the GITS corridor sections)
     -> weekday hourly GITS ratio k = free-flow / hourly speed, period min/median/max (proxy);
   * other links and unmatched samples -> residential assumption (1.0, 1.1, 1.2).
   Shares are length shares; both classes use one common random quantile per draw
   (same-day congestion moves together, a conservative choice).
3. No matching file -> residential assumption for the whole route.
"""
from __future__ import annotations

import csv
import math
from datetime import date
from statistics import fmean, multimode

import numpy as np

from modules.settings import PROJECT_DIR

MATCHING = PROJECT_DIR / "data/processed/route_link_matching.csv"
CONGESTION = PROJECT_DIR / "data/processed/congestion_by_hour.csv"
OBSERVED = PROJECT_DIR / "data/assumptions/travel_time_observed.csv"
RESIDENTIAL_K = (1.0, 1.1, 1.2)
ARTERIAL_RANKS = {"101", "102", "103"}
MIN_OBSERVED = 3
PERIOD_HOURS = {"출근": range(7, 10), "퇴근": range(17, 20)}
OBSERVED_FIELDS = ["측정일", "출발지", "도착지", "실측소요분", "OSRM소요분", "검증상태", "출처",
                   "노선", "시간대", "출발시각", "측정방식", "메모"]
RANK_NAMES = {"101": "고속국도", "102": "도시고속도로", "103": "일반국도", "104": "특별·광역시도",
              "105": "국가지원지방도", "106": "지방도", "107": "시군도"}


def corridor_k(period):
    hours = PERIOD_HOURS[period]
    with CONGESTION.open(encoding="utf-8-sig", newline="") as handle:
        values = sorted(float(r["k"]) for r in csv.DictReader(handle)
                        if int(r["시간"]) in hours and r.get("k") not in (None, ""))
    if not values:
        raise ValueError(f"congestion_by_hour.csv에 {period} 혼잡값이 없습니다.")
    return (values[0], float(np.median(values)), values[-1]), len(values)


def matching_rows(route_id=None):
    if not MATCHING.exists():
        return []
    with MATCHING.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if route_id is None or r["route_id"] == route_id]


def composition(route_id):
    rows = matching_rows(route_id)
    total = sum(float(r["length_m"]) for r in rows)
    if not total:
        return None
    arterial = sum(float(r["length_m"]) for r in rows if r["road_rank"] in ARTERIAL_RANKS)
    unmatched = sum(float(r["length_m"]) for r in rows if not r["link_id"])
    return dict(arterial=arterial / total, local=(total - arterial - unmatched) / total,
                unmatched=unmatched / total, length_m=total, rows=rows)


def road_table(route_id):
    """Per road: length, rank class and which congestion source applies."""
    grouped = {}
    for r in matching_rows(route_id):
        key = (r["road_name"], r["road_rank"])
        grouped[key] = grouped.get(key, 0.0) + float(r["length_m"])
    total = sum(grouped.values()) or 1
    return [dict(road=name, rank=RANK_NAMES.get(rank, "미매칭" if not rank else rank), length_m=length,
                 share=length / total,
                 source="GITS 시간대 속도(동급 간선 대리값)" if rank in ARTERIAL_RANKS else
                        "가정값 1.0/1.1/1.2 · 시간대 자료 없음 → 실측 필요")
            for (name, rank), length in sorted(grouped.items(), key=lambda x: -x[1])]


def read_observations():
    if not OBSERVED.exists():
        return []
    with OBSERVED.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def observed_ratios(route_id, period):
    ratios = []
    for r in read_observations():
        if r.get("노선") != route_id or r.get("시간대") != period:
            continue
        try:
            observed, model = float(r["실측소요분"]), float(r["OSRM소요분"])
        except (TypeError, ValueError, KeyError):
            continue
        if (r.get("검증상태") == "verified" and str(r.get("출처", "")).strip() not in ("", "missing")
                and math.isfinite(observed) and math.isfinite(model) and min(observed, model) > 0):
            ratios.append(observed / model)
    return ratios


def triangle_from(ratios):
    low, high = min(ratios), max(ratios)
    modes = multimode(ratios)
    mode = modes[0] if len(modes) == 1 else max(low, min(high, 3 * fmean(ratios) - low - high))
    return low, mode, high


def _inverse_triangular(u, k):
    lo, mode, hi = k
    if hi == lo:
        return np.full_like(u, lo, dtype=float)
    cut = (mode - lo) / (hi - lo)
    left = lo + np.sqrt(u * (hi - lo) * (mode - lo))
    right = hi - np.sqrt((1 - u) * (hi - lo) * (hi - mode))
    return np.where(u < cut, left, right)


def route_factor(route_id, period):
    """Return dict(kind, k=(lo, mode, hi), basis, sample(u) -> factors)."""
    ratios = observed_ratios(route_id, period)
    if len(ratios) >= MIN_OBSERVED:
        k = triangle_from(ratios)
        return dict(kind="observed", k=k, n=len(ratios), sample=lambda u: _inverse_triangular(u, k),
                    basis=f"현장 실측 {len(ratios)}건(실측÷모형 비율 최소/최빈/최대) · {route_id} {period}")
    comp = composition(route_id)
    if comp is None:
        return dict(kind="assumption", k=RESIDENTIAL_K, n=0, sample=lambda u: _inverse_triangular(u, RESIDENTIAL_K),
                    basis="도로 매칭 자료 없음 · 단지내 가정값 1.0/1.1/1.2")
    corridor, count = corridor_k(period)
    a = comp["arterial"]
    k = tuple(a * c + (1 - a) * r for c, r in zip(corridor, RESIDENTIAL_K))
    note = (f"도로 구성: 간선(국도·고속도로) {a:.0%} → GITS 평일 {period} 시간대 속도비 k=자유류/시간대속도 "
            f"{corridor[0]:.2f}/{corridor[1]:.2f}/{corridor[2]:.2f}({count}개 값, 동급 간선 대리값), "
            f"그 외 {1 - a:.0%} → 가정값 1.0/1.1/1.2 · 길이 가중, 같은 날 혼잡 동조 가정")
    if len(ratios):
        note += f" · 실측 {len(ratios)}건 입력됨({MIN_OBSERVED}건부터 반영)"
    return dict(kind="composite", k=k, n=len(ratios), arterial=a,
                sample=lambda u: a * _inverse_triangular(u, corridor) + (1 - a) * _inverse_triangular(u, RESIDENTIAL_K),
                basis=note)


def append_observation(row):
    """Validate and append one field measurement (UTF-8 BOM CSV, header preserved)."""
    try:
        observed, model = float(row["실측소요분"]), float(row["OSRM소요분"])
    except (TypeError, ValueError, KeyError):
        raise ValueError("실측·모형 소요시간은 숫자여야 합니다.") from None
    if not (math.isfinite(observed) and math.isfinite(model) and observed > 0 and model > 0):
        raise ValueError("실측·모형 소요시간은 0보다 커야 합니다.")
    if row.get("검증상태") == "verified" and not str(row.get("출처", "")).strip():
        raise ValueError("검증 완료로 저장하려면 출처(측정자·기록 방법)를 입력하세요.")
    if not isinstance(row.get("측정일"), (str, date)):
        raise ValueError("측정일이 필요합니다.")
    existing = read_observations()
    header = OBSERVED_FIELDS
    if OBSERVED.exists():
        with OBSERVED.open(encoding="utf-8-sig", newline="") as handle:
            current = next(csv.reader(handle), [])
        header = current + [f for f in OBSERVED_FIELDS if f not in current] if current else OBSERVED_FIELDS
    OBSERVED.parent.mkdir(parents=True, exist_ok=True)
    with OBSERVED.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)
        writer.writerow({k: str(v) for k, v in row.items()})

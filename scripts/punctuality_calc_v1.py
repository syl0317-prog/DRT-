"""Calculate simulated DRT-to-tram punctuality from local OSRM cache only."""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "sewook31"
STOPS = APP / "data" / "drt_stops.csv"
CACHE = APP / "data" / "osrm_cache.json"
PARAMS = ROOT / "data" / "assumptions" / "sim_params.json"
CONGESTION = ROOT / "data" / "processed" / "congestion_by_hour.csv"
OUT_CSV = ROOT / "data" / "processed" / "punctuality_results.csv"
OUT_PNG = ROOT / "data" / "processed" / "punctuality_chart.png"
HEADERS = [
    "정류장", "시간대", "구간유형", "혼잡수준", "합승수", "여유분",
    "놓칠확률", "평균대기분", "기준대기분", "가정"
]
REPS = 10_000
HEADWAY = 10.0
PASSENGER_DELAY = 2.0


def cache_key(a, b):
    return ";".join(f"{float(lat):.6f},{float(lon):.6f}" for lat, lon in (a, b))


def haversine(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def read_inputs():
    with STOPS.open(encoding="utf-8-sig", newline="") as f:
        stops = list(csv.DictReader(f))
    with CACHE.open(encoding="utf-8") as f:
        cache = json.load(f)
    config = json.loads(PARAMS.read_text(encoding="utf-8"))
    with CONGESTION.open(encoding="utf-8-sig", newline="") as f:
        congestion = list(csv.DictReader(f))
    tram = [r for r in stops if r["stop_type"] == "tram"]
    drt = [r for r in stops if r["stop_type"] == "drt"]
    routes = []
    skipped = []
    for stop in drt:
        a = (float(stop["latitude"]), float(stop["longitude"]))
        nearest = min(tram, key=lambda r: haversine(a, (float(r["latitude"]), float(r["longitude"]))))
        b = (float(nearest["latitude"]), float(nearest["longitude"]))
        route = cache.get(cache_key(a, b)) or cache.get(cache_key(b, a))
        if not route or route.get("duration_min") is None:
            skipped.append(stop["stop_name"])
            continue
        routes.append((stop["stop_name"], float(route["duration_min"]), nearest["stop_name"]))
    return routes, skipped, config, congestion


def factor_ranges(rows, hours):
    # 12개 구간별 hours 시간대의 평균 k 산출 후, 12개 구간의 최솟값, 중앙값(최빈값), 최댓값 계산
    road_k = {}
    for r in rows:
        h = int(r["시간"])
        if h in hours and r.get("k") not in (None, ""):
            seg = r["도로구간"]
            road_k.setdefault(seg, []).append(float(r["k"]))
    if not road_k:
        raise ValueError(f"congestion_by_hour.csv에 {hours}시 혼잡값이 없습니다")
    seg_means = [statistics.mean(vals) for vals in road_k.values() if vals]
    seg_means.sort()
    return min(seg_means), statistics.median(seg_means), max(seg_means)


def simulate(routes, config, congestion):
    rng = random.Random(42)
    dwell = float(config.get("dwell_minutes", {}).get("value", 1))
    groups = [("출근", [7, 8, 9]), ("퇴근", [17, 18, 19])]
    results = []
    for period, hours in groups:
        corridor = factor_ranges(congestion, hours)
        for stop_name, duration, _tram_name in routes:
            for segment in ("단지내", "간선연계"):
                bounds = (1.0, 1.1, 1.2) if segment == "단지내" else corridor
                lo_all, mode_all, hi_all = bounds
                scenarios = {
                    "min": (lo_all, lo_all, mode_all),
                    "mode": (lo_all, mode_all, hi_all),
                    "max": (mode_all, hi_all, hi_all),
                }
                for level, (lo, mode, hi) in scenarios.items():
                    for passengers in (0, 1, 2):
                        deltas = [
                            duration * (rng.triangular(lo, hi, mode) - mode)
                            + passengers * PASSENGER_DELAY
                            for _ in range(REPS)
                        ]
                        for buffer in range(11):
                            missed = 0
                            waits = 0.0
                            for delta in deltas:
                                lateness = delta - buffer
                                if lateness > 1e-12:
                                    missed += 1
                                    remainder = lateness % HEADWAY
                                    waits += HEADWAY - remainder if remainder > 1e-12 else HEADWAY
                                else:
                                    waits += -lateness
                            assumptions = (
                                f"T={duration:.3f}분 OSRM 캐시; 삼각분포 k={lo:.4f}/{mode:.4f}/{hi:.4f}; "
                                f"정차={dwell:g}분; 합승={PASSENGER_DELAY:g}분/인; 배차={HEADWAY:g}분; "
                                "요일·시간 구간 대응 assumption; 운행 실측 아님"
                            )
                            results.append({
                                "정류장": stop_name,
                                "시간대": period,
                                "구간유형": segment,
                                "혼잡수준": level,
                                "합승수": passengers,
                                "여유분": buffer,
                                "놓칠확률": missed / REPS,
                                "평균대기분": waits / REPS,
                                "기준대기분": HEADWAY / 2,
                                "가정": assumptions,
                            })
    return results


def setup_matplotlib_font():
    # Try Korean fonts
    korean_fonts = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Dotum"]
    available_fonts = {f.name for f in fm.fontManager.ttflist}
    for font_name in korean_fonts:
        if font_name in available_fonts:
            plt.rcParams["font.family"] = font_name
            plt.rcParams["axes.unicode_minus"] = False
            return True
    return False


def draw_chart(rows):
    has_korean = setup_matplotlib_font()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6), dpi=150)

    # Styles for series
    colors = {
        ("출근", "단지내"): "#1b9e77",
        ("출근", "간선연계"): "#386cb0",
        ("퇴근", "단지내"): "#7570b3",
        ("퇴근", "간선연계"): "#d95f02",
    }
    linestyles = {0: "-", 2: "--"}

    buffers = list(range(11))

    for (period, segment), color in colors.items():
        for passengers in (0, 2):
            ls = linestyles[passengers]
            p_label = f"{period}-{segment} (합승 {passengers}명)" if has_korean else f"{period}-{segment} (pool={passengers})"
            # Average across stops for mode level
            miss_rates = []
            mean_waits = []
            for b in buffers:
                subset = [
                    r for r in rows
                    if r["시간대"] == period
                    and r["구간유형"] == segment
                    and r["혼잡수준"] == "mode"
                    and r["합승수"] == passengers
                    and r["여유분"] == b
                ]
                if subset:
                    miss_rates.append(sum(r["놓칠확률"] for r in subset) / len(subset))
                    mean_waits.append(sum(r["평균대기분"] for r in subset) / len(subset))
                else:
                    miss_rates.append(0.0)
                    mean_waits.append(0.0)

            ax1.plot(buffers, miss_rates, label=p_label, color=color, linestyle=ls, linewidth=2, marker="o", markersize=4)
            ax2.plot(buffers, mean_waits, label=p_label, color=color, linestyle=ls, linewidth=2, marker="o", markersize=4)

    # Baseline reference line on ax2
    baseline_label = "기준선: 임의도착 평균대기 5분" if has_korean else "Baseline: Random Arrival (5 min)"
    ax2.axhline(5.0, color="#d32f2f", linestyle=":", linewidth=2.5, label=baseline_label)

    # Subplot 1 settings
    title1 = "여유시간(b)별 트램 놓칠 확률" if has_korean else "Tram Miss Probability vs. Slack (b)"
    xlabel = "환승 여유시간 b (분)" if has_korean else "Transfer Slack b (min)"
    ylabel1 = "놓칠 확률" if has_korean else "Miss Probability"
    ax1.set_title(title1, fontsize=13, fontweight="bold", pad=10)
    ax1.set_xlabel(xlabel, fontsize=11)
    ax1.set_ylabel(ylabel1, fontsize=11)
    ax1.set_xticks(buffers)
    ax1.set_ylim(-0.02, 1.05)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(fontsize=8, loc="upper right")

    # Subplot 2 settings
    title2 = "여유시간(b)별 평균 환승 대기시간" if has_korean else "Mean Transfer Waiting Time vs. Slack (b)"
    ylabel2 = "평균 대기시간 (분)" if has_korean else "Mean Waiting Time (min)"
    ax2.set_title(title2, fontsize=13, fontweight="bold", pad=10)
    ax2.set_xlabel(xlabel, fontsize=11)
    ax2.set_ylabel(ylabel2, fontsize=11)
    ax2.set_xticks(buffers)
    ax2.set_ylim(0, 11)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(fontsize=8, loc="upper right")

    fig.suptitle(
        "DRT-트램 환승 정시성 시뮬레이션 결과 (혼잡수준: mode)" if has_korean
        else "DRT-Tram Transfer Punctuality Simulation (Congestion: mode)",
        fontsize=15, fontweight="bold", y=0.98
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=200)
    plt.close()


def main():
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    try:
        routes, skipped, config, congestion = read_inputs()
    except FileNotFoundError as exc:
        raise SystemExit(f"필수 입력 파일 없음: {exc.filename}")

    rows = simulate(routes, config, congestion)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    draw_chart(rows)

    print(f"시뮬레이션 행: {len(rows)}; 결과: {OUT_CSV}; 그래프: {OUT_PNG}")
    if skipped:
        print("OSRM 캐시에 경로가 없어 건너뜀: " + ", ".join(skipped))
    else:
        print("캐시 경로를 찾지 못해 건너뛴 정류장: 없음 (전체 4개 가상정류장 캐시 보유)")

    if not rows:
        print("경고: 결과가 비었습니다.")
        return

    print("\n[요약 표] 혼잡수준=mode, 정류장 전체 평균")
    print("시간대 | 구간유형 | 합승 | b=0 | b=2 | b=3 | b=5 | b=8 | 기준대기")
    summary_data = []
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                row_cells = []
                for buffer in (0, 2, 3, 5, 8):
                    selected = [
                        r for r in rows
                        if r["시간대"] == period
                        and r["구간유형"] == segment
                        and r["혼잡수준"] == "mode"
                        and r["합승수"] == passengers
                        and r["여유분"] == buffer
                    ]
                    missed = sum(r["놓칠확률"] for r in selected) / len(selected)
                    wait = sum(r["평균대기분"] for r in selected) / len(selected)
                    row_cells.append(f"{missed:.1%}/{wait:.2f}분")
                line_str = f"{period} | {segment} | {passengers}명 | " + " | ".join(row_cells) + " | 5.00분"
                print(line_str)

    print("\n[놓칠 확률 5% 이하 최소 여유시간 b] (혼잡수준=mode):")
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                parts = []
                for stop in sorted({r["정류장"] for r in rows}):
                    selected = [
                        r for r in rows
                        if r["정류장"] == stop
                        and r["시간대"] == period
                        and r["구간유형"] == segment
                        and r["혼잡수준"] == "mode"
                        and r["합승수"] == passengers
                    ]
                    safe = [r["여유분"] for r in selected if r["놓칠확률"] <= 0.05]
                    parts.append(f"{stop}: b>={min(safe)}분" if safe else f"{stop}: 10분 내 없음")
                # Also overall average
                avg_safe = []
                for b in range(11):
                    sel = [
                        r for r in rows
                        if r["시간대"] == period
                        and r["구간유형"] == segment
                        and r["혼잡수준"] == "mode"
                        and r["합승수"] == passengers
                        and r["여유분"] == b
                    ]
                    if sel and (sum(r["놓칠확률"] for r in sel) / len(sel)) <= 0.05:
                        avg_safe.append(b)
                avg_min = f"b>={min(avg_safe)}분" if avg_safe else "10분 내 없음"
                print(f"{period}/{segment}/합승 {passengers}명: 평균 {avg_min} (정류장별: {', '.join(parts)})")

    # Monotonicity check
    monotonic = True
    groups = {}
    for r in rows:
        key = (r["정류장"], r["시간대"], r["구간유형"], r["혼잡수준"], r["합승수"])
        groups.setdefault(key, []).append(r)
    for values in groups.values():
        values.sort(key=lambda r: r["여유분"])
        for a, b in zip(values, values[1:]):
            if a["놓칠확률"] < b["놓칠확률"]:
                monotonic = False
                break
    print(f"\n여유시간(b) 증가 시 놓칠 확률 단조 감소 여부: {'예 (항상 감소하거나 유지)' if monotonic else '아니요'}")


if __name__ == "__main__":
    main()

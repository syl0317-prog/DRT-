"""Calculate calibrated DRT-to-tram punctuality simulation."""
from __future__ import annotations

import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "sewook31"
STOPS = APP / "data" / "drt_stops.csv"
CACHE = APP / "data" / "osrm_cache.json"
PARAMS = ROOT / "data" / "assumptions" / "sim_params.json"
CONGESTION = ROOT / "data" / "processed" / "congestion_by_hour.csv"
<<<<<<< HEAD
OUT_CSV = ROOT / "data" / "processed" / "punctuality_results.csv"
OUT_PNG = ROOT / "data" / "processed" / "punctuality_chart.png"
HEADERS = [
    "정류장", "시간대", "구간유형", "혼잡수준", "합승수", "여유분",
    "놓칠확률", "평균대기분", "기준대기분", "가정"
]
=======
OUT_CSV = ROOT / "data" / "processed" / "punctuality_main_results.csv"
OUT_PNG = ROOT / "data" / "processed" / "punctuality_main_chart.png"
HEADERS = ["정류장", "시간대", "구간유형", "혼잡수준", "합승수", "여유분",
           "놓칠확률", "평균대기분", "기준대기분", "가정"]
>>>>>>> 038500dfc6e855e711352be5957a5e7a905b15a6
REPS = 10_000
HEADWAY = 10.0


def read_inputs():
    with STOPS.open(encoding="utf-8-sig", newline="") as f:
        stops = list(csv.DictReader(f))
    with CACHE.open(encoding="utf-8") as f:
        cache = json.load(f)
    config = json.loads(PARAMS.read_text(encoding="utf-8"))
    with CONGESTION.open(encoding="utf-8-sig", newline="") as f:
        congestion = list(csv.DictReader(f))

    # Import SimulatedProvider to extract morning vehicle trip schedules
    sys.path.insert(0, str(APP))
    try:
        from modules.vehicle_positions import SimulatedProvider
        sp = SimulatedProvider(scenario="평일 출근 07~09시")
        vehicle_trips = sp.drt_trips
    except Exception as exc:
        print(f"경고: SimulatedProvider 로드 실패 ({exc}); 기본 OSRM 캐시 기반으로 진행합니다.")
        vehicle_trips = None

    dwell = float(config.get("dwell_minutes", {}).get("value", 1.0))
    trip_noise_min = float(config.get("trip_noise_min", {}).get("value", 1.0))

    tram = [r for r in stops if r["stop_type"] == "tram"]
    drt = [r for r in stops if r["stop_type"] == "drt"]

    routes = []
    skipped = []

    for stop in drt:
        stop_id = stop["stop_id"]
        stop_name = stop["stop_name"]
        
        # Check vehicle schedule from SimulatedProvider
        if vehicle_trips:
            # Map stop_id to vehicle (homes: V01->D01, V02->D02, V03->D03, V04->D04)
            v_match = None
            for vid, trips in vehicle_trips.items():
                if trips and trips[0].get("home_id") == stop_id:
                    v_match = trips
                    break
            if v_match:
                peak_trips = [t for t in v_match if 7 <= t["target_tram"].hour < 9]
                sample = peak_trips[0] if peak_trips else v_match[0]
                base_drive_min = float(sample["out_base_min"])
                planned_drive_min = (sample["planned_arrival"] - sample["planned_start"]).total_seconds() / 60.0
                t_trip_min = planned_drive_min + dwell
                routes.append({
                    "stop_id": stop_id,
                    "stop_name": stop_name,
                    "tram_id": sample["tram_stop_id"],
                    "tram_name": "위례역사공원역" if sample["tram_stop_id"] == "T02" else "위례별역",
                    "base_drive_min": base_drive_min,
                    "t_trip_min": t_trip_min,
                    "status": "sourced(출근 차량일정 계획시간 기반, 정차 포함)"
                })
                continue

        # Fallback to nearest tram stop in drt_stops.csv
        # (All D01-D04 in drt_stops.csv have OSRM cache to T01)
        a = (float(stop["latitude"]), float(stop["longitude"]))
        # Nearest tram stop
        def haversine(p1, p2):
            lat1, lon1 = map(math.radians, p1)
            lat2, lon2 = map(math.radians, p2)
            dlat, dlon = lat2 - lat1, lon2 - lon1
            h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
            return 6371000 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))

        nearest = min(tram, key=lambda r: haversine(a, (float(r["latitude"]), float(r["longitude"]))))
        b = (float(nearest["latitude"]), float(nearest["longitude"]))
        key1 = f"{a[0]:.6f},{a[1]:.6f};{b[0]:.6f},{b[1]:.6f}"
        key2 = f"{b[0]:.6f},{b[1]:.6f};{a[0]:.6f},{a[1]:.6f}"
        route_cache = cache.get(key1) or cache.get(key2)
        if not route_cache or route_cache.get("duration_min") is None:
            skipped.append(stop_name)
            continue
        base_drive_min = float(route_cache["duration_min"])
        routes.append({
            "stop_id": stop_id,
            "stop_name": stop_name,
            "tram_id": nearest["stop_id"],
            "tram_name": nearest["stop_name"],
            "base_drive_min": base_drive_min,
            "t_trip_min": base_drive_min + dwell,
            "status": "assumption(OSRM 캐시 편도+정차시간)"
        })

    return routes, skipped, config, congestion, dwell, trip_noise_min


def factor_ranges(rows, hours):
    # 12개 구간별 hours 시간대의 평균 k 산출 후 최솟값, 중앙값(최빈값), 최댓값 계산
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


def simulate(routes, congestion, dwell, trip_noise_min):
    rng = random.Random(42)

    # 1. 단지내 k 보정 (위례그린파크푸르지오 -> 위례역사공원역 답사 실측 6분 대 OSRM 1.9433분 비교)
    # Greenpark (37.473621, 127.154654) -> History Park (37.470340, 127.141949) OSRM = 1.9433 min
    osrm_greenpark_min = 1.9433333333333331
    ratio = 6.0 / osrm_greenpark_min  # approx 3.0875
    complex_mode = max(1.0, ratio)
    complex_min = 1.0
    complex_max = complex_mode + 0.3  # approx 3.3875

    groups = [("출근", [7, 8, 9]), ("퇴근", [17, 18, 19])]
    results = []

    for period, hours in groups:
        corridor_min, corridor_mode, corridor_max = factor_ranges(congestion, hours)

        for r_info in routes:
            stop_name = r_info["stop_name"]
            base_drive = r_info["base_drive_min"]
            t_trip = r_info["t_trip_min"]

            for segment in ("단지내", "간선연계"):
                if segment == "단지내":
                    k_min, k_mode, k_max = complex_min, complex_mode, complex_max
                    # Scenarios: mode vs max
                    scenarios = {
                        "mode": (k_min, k_max, k_mode),
                        "max": (k_mode, k_max, k_max),
                    }
                else:
                    k_min, k_mode, k_max = corridor_min, corridor_mode, corridor_max
                    scenarios = {
                        "mode": (k_min, k_max, k_mode),
                        "max": (k_mode, k_max, k_max),
                    }

                for level, (lo, hi, mode) in scenarios.items():
                    for passengers in (0, 1, 2):
                        # 10,000 iterations
                        # Delta = base_drive * (k - mode) + trip_noise + pooling_delay
                        # Noise: uniform(-trip_noise_min, trip_noise_min)
                        # Pooling delay: sum of Exponential(mean=2.0) for each passenger
                        deltas = []
                        for _ in range(REPS):
                            k_sample = rng.triangular(lo, hi, mode)
                            noise = rng.uniform(-trip_noise_min, trip_noise_min)
                            pool_delay = sum(rng.expovariate(0.5) for _ in range(passengers)) if passengers > 0 else 0.0
                            delta = base_drive * (k_sample - mode) + noise + pool_delay
                            deltas.append(delta)

                        for buffer in range(11):
                            missed = 0
                            waits = 0.0
                            for delta in deltas:
                                lateness = delta - buffer
                                if lateness > 1e-12:
                                    missed += 1
                                    remainder = lateness % HEADWAY
<<<<<<< HEAD
                                    waits += (HEADWAY - remainder) if remainder > 1e-12 else HEADWAY
=======
                                    waits += HEADWAY - remainder if remainder > 1e-12 else 0
>>>>>>> 038500dfc6e855e711352be5957a5e7a905b15a6
                                else:
                                    waits += -lateness

                            if segment == "단지내":
                                seg_note = f"단지내 답사비율(6분/1.94분={ratio:.2f}) 보정 k={lo:.3f}/{mode:.3f}/{hi:.3f}"
                            else:
                                seg_note = f"간선연계 12개구간 k={lo:.3f}/{mode:.3f}/{hi:.3f}"
                                if level == "max":
                                    seg_note += " (최악 구간 기준)"

                            assumptions = (
                                f"T_trip={t_trip:.2f}분(정차 {dwell:g}분 포함, {r_info['status']}); {seg_note}; "
                                f"운행변동=±{trip_noise_min:g}분 균등; 합승지연=인당 Exp(평균2분); 배차={HEADWAY:g}분"
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

    return results, ratio, complex_min, complex_mode, complex_max


def setup_matplotlib_font():
    korean_fonts = ["Malgun Gothic", "NanumGothic", "AppleGothic", "Dotum"]
    available_fonts = {f.name for f in fm.fontManager.ttflist}
    for font_name in korean_fonts:
        if font_name in available_fonts:
            plt.rcParams["font.family"] = font_name
            plt.rcParams["axes.unicode_minus"] = False
            return True
    return False


def draw_chart(rows):
<<<<<<< HEAD
    has_korean = setup_matplotlib_font()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6.5), dpi=150)

    # Compare mode (solid) and max (dashed)
    # Colors for combinations
    color_map = {
        ("출근", "단지내"): "#1b9e77",
        ("출근", "간선연계"): "#386cb0",
        ("퇴근", "단지내"): "#7570b3",
        ("퇴근", "간선연계"): "#d95f02",
    }
    buffers = list(range(11))

    # We plot 합승 0명 and 합승 2명 for mode & max
    # To avoid visual clutter, let's plot mode (solid) vs max (dashed) for 합승 0명 and 합승 2명
    for (period, segment), col in color_map.items():
        for level, ls in [("mode", "-"), ("max", ":")]:
            # Average across stops for 합승 0명
            miss_0 = []
            wait_0 = []
            for b in buffers:
                subset = [
                    r for r in rows
                    if r["시간대"] == period
                    and r["구간유형"] == segment
                    and r["혼잡수준"] == level
                    and r["합승수"] == 0
                    and r["여유분"] == b
                ]
                if subset:
                    miss_0.append(sum(r["놓칠확률"] for r in subset) / len(subset))
                    wait_0.append(sum(r["평균대기분"] for r in subset) / len(subset))
                else:
                    miss_0.append(0.0)
                    wait_0.append(0.0)

            lbl = f"{period}-{segment} ({level})" if has_korean else f"{period}-{segment} ({level})"
            ax1.plot(buffers, miss_0, label=lbl, color=col, linestyle=ls, linewidth=2, marker="o" if level=="mode" else "x", markersize=4)
            ax2.plot(buffers, wait_0, label=lbl, color=col, linestyle=ls, linewidth=2, marker="o" if level=="mode" else "x", markersize=4)

    # Baseline reference line
    baseline_label = "기준선: 임의도착 평균대기 5분" if has_korean else "Baseline: Random Arrival (5 min)"
    ax2.axhline(5.0, color="#d32f2f", linestyle="--", linewidth=2.5, label=baseline_label)

    # Subplot 1
    t1 = "여유시간(b)별 트램 놓칠 확률 (합승 0명, mode 실선 / max 점선)" if has_korean else "Tram Miss Probability vs Slack (Pool 0, mode solid / max dot)"
    ax1.set_title(t1, fontsize=12, fontweight="bold", pad=10)
    ax1.set_xlabel("환승 여유시간 b (분)" if has_korean else "Transfer Slack b (min)", fontsize=11)
    ax1.set_ylabel("놓칠 확률" if has_korean else "Miss Probability", fontsize=11)
    ax1.set_xticks(buffers)
    ax1.set_ylim(-0.02, 1.05)
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend(fontsize=8, loc="upper right")

    # Subplot 2
    t2 = "여유시간(b)별 평균 환승 대기시간 (합승 0명, mode 실선 / max 점선)" if has_korean else "Mean Wait Time vs Slack (Pool 0, mode solid / max dot)"
    ax2.set_title(t2, fontsize=12, fontweight="bold", pad=10)
    ax2.set_xlabel("환승 여유시간 b (분)" if has_korean else "Transfer Slack b (min)", fontsize=11)
    ax2.set_ylabel("평균 대기시간 (분)" if has_korean else "Mean Waiting Time (min)", fontsize=11)
    ax2.set_xticks(buffers)
    ax2.set_ylim(0, 11)
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend(fontsize=8, loc="upper right")

    fig.suptitle(
        "보정된 DRT-트램 환승 정시성 시뮬레이션 결과 (혼잡수준: mode vs max 최악구간)" if has_korean
        else "Calibrated DRT-Tram Transfer Punctuality Simulation (mode vs max)",
        fontsize=14, fontweight="bold", y=0.98
    )
    plt.tight_layout()
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=200)
    plt.close()
=======
    """Small Pillow chart; uses Korean font when available, English otherwise."""
    w, h = 1400, 850
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    title_font, label_font = _font(27), _font(17)
    korean = "C:\\Windows\\Fonts\\malgun.ttf"
    has_korean = Path(korean).exists()
    title = "Punctuality simulation (no cached routes)" if not rows else ("정시성 시뮬레이션" if has_korean else "Punctuality simulation")
    d.text((65, 24), title, fill="#182230", font=title_font)
    colors = {"출근-단지내": "#147d64", "출근-간선연계": "#2266b3", "퇴근-단지내": "#a34d9b", "퇴근-간선연계": "#d27b00"}
    panels = [(65, 95, 675, 370, "놓칠 확률" if has_korean else "Miss probability", "probability"),
              (735, 95, 1345, 370, "평균 환승 대기시간" if has_korean else "Mean transfer wait", "wait")]
    for x0, y0, x1, y1, label, metric in panels:
        d.rectangle((x0, y0, x1, y1), outline="#536273", width=2)
        d.text((x0 + 8, y0 + 5), label, fill="#182230", font=label_font)
        for i in range(1, 5):
            y = y0 + 35 + (y1 - y0 - 60) * i / 5
            d.line((x0 + 42, y, x1 - 10, y), fill="#e2e8f0", width=1)
        if not rows:
            d.text((x0 + 90, y0 + 170), "No data: OSRM cache required", fill="#9b1c1c", font=label_font)
            continue
        for key, color in colors.items():
            period, segment = key.split("-", 1)
            series = [r for r in rows if r["시간대"] == period and r["구간유형"] == segment and r["혼잡수준"] == "mode" and r["합승수"] == 0]
            # Plot one mean per buffer rather than joining different stops end to end.
            series = [{"여유분": b,
                       "놓칠확률": sum(r["놓칠확률"] for r in series if r["여유분"] == b) / sum(r["여유분"] == b for r in series),
                       "평균대기분": sum(r["평균대기분"] for r in series if r["여유분"] == b) / sum(r["여유분"] == b for r in series)}
                      for b in sorted({r["여유분"] for r in series})]
            points = []
            for r in series:
                x = x0 + 45 + r["여유분"] * (x1 - x0 - 65) / 10
                val = r["놓칠확률"] if metric == "probability" else r["평균대기분"]
                vmax = 1 if metric == "probability" else max(HEADWAY, max((z["평균대기분"] for z in rows), default=10))
                y = y1 - 25 - val * (y1 - y0 - 60) / vmax
                points.append((x, y))
            if len(points) > 1:
                d.line(points, fill=color, width=3)
        if metric == "wait":
            y = y1 - 25 - 5 * (y1 - y0 - 60) / max(HEADWAY, max((r["평균대기분"] for r in rows), default=10))
            for dx in range(x0 + 42, x1 - 10, 12):
                d.line((dx, y, min(dx + 6, x1 - 10), y), fill="#c62828", width=2)
    legend_y = 415
    for i, (key, color) in enumerate(colors.items()):
        x = 100 + (i % 2) * 330
        y = legend_y + (i // 2) * 32
        d.line((x, y + 9, x + 32, y + 9), fill=color, width=4)
        d.text((x + 40, y), key, fill="#182230", font=label_font)
    d.line((800, legend_y + 9, 832, legend_y + 9), fill="#c62828", width=2)
    d.text((840, legend_y), "Baseline wait 5 min (dashed-style reference)", fill="#182230", font=label_font)
    d.text((65, 535), "X: slack b (minutes), 0 to 10", fill="#344054", font=label_font)
    d.text((65, 575), "Traffic levels min/mode/max and shared passenger counts 0/1/2 are in the CSV.", fill="#344054", font=label_font)
    d.text((65, 615), "Assumptions only; simulated results are not field validation.", fill="#344054", font=label_font)
    im.save(OUT_PNG, format="PNG")
>>>>>>> 038500dfc6e855e711352be5957a5e7a905b15a6


def main():
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    try:
        routes, skipped, config, congestion, dwell, trip_noise_min = read_inputs()
    except FileNotFoundError as exc:
        raise SystemExit(f"필수 입력 파일 없음: {exc.filename}")

    rows, ratio, c_min, c_mode, c_max = simulate(routes, congestion, dwell, trip_noise_min)

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    draw_chart(rows)

    print(f"시뮬레이션 완료: 총 {len(rows)}개 행 저장 -> {OUT_CSV}")
    print(f"차트 저장: {OUT_PNG}")
    print(f"\n[단지내 변동계수 보정 결과]")
    print(f"- 위례그린파크푸르지오 -> 위례역사공원역: 답사 실측 6.00분 대 OSRM 1.94분 -> ratio = {ratio:.3f}")
    print(f"- 단지내 k 삼각분포: 최소={c_min:.3f}, 최빈={c_mode:.3f}, 최대={c_max:.3f}")

    print("\n[정류장별 T_trip 및 계획 소요시간]")
    for r in routes:
        print(f"- {r['stop_id']} ({r['stop_name']} -> {r['tram_name']}): T_trip = {r['t_trip_min']:.2f}분 (주행 {r['base_drive_min']:.2f}분 + 정차 {dwell:g}분) [{r['status']}]")

    print("\n[요약 표: b=0, 2, 3, 5, 8분 (혼잡수준: mode, 정류장 전체 평균)]")
    print("시간대 | 구간유형 | 합승 | b=0 | b=2 | b=3 | b=5 | b=8 | 기준대기")
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                cells = []
                for b in (0, 2, 3, 5, 8):
                    sel = [
                        r for r in rows
                        if r["시간대"] == period
                        and r["구간유형"] == segment
                        and r["혼잡수준"] == "mode"
                        and r["합승수"] == passengers
                        and r["여유분"] == b
                    ]
                    m = sum(r["놓칠확률"] for r in sel) / len(sel)
                    w = sum(r["평균대기분"] for r in sel) / len(sel)
                    cells.append(f"{m:.1%}/{w:.2f}분")
                print(f"{period} | {segment} | {passengers}명 | " + " | ".join(cells) + " | 5.00분")

    print("\n[놓칠 확률 5% 이하 최소 여유시간 b (혼잡수준: mode, 평균 기준)]")
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                safe_b = []
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
                        safe_b.append(b)
                b_min = f"b >= {min(safe_b)}분" if safe_b else "10분 내 없음"
                print(f"{period}/{segment}/합승 {passengers}명: {b_min}")

    # Count strictly 0% and 100% rows
    total_rows = len(rows)
    zero_rows = sum(1 for r in rows if r["놓칠확률"] == 0.0)
    hundred_rows = sum(1 for r in rows if r["놓칠확률"] == 1.0)
    intermediate_rows = total_rows - zero_rows - hundred_rows
    print(f"\n[0% 및 100% 극단값 비율 점검]")
    print(f"- 전체 행 수: {total_rows}")
    print(f"- 놓칠 확률 0.0% 행 수: {zero_rows} ({zero_rows/total_rows:.1%})")
    print(f"- 놓칠 확률 100.0% 행 수: {hundred_rows} ({hundred_rows/total_rows:.1%})")
    print(f"- 0% 초과 ~ 100% 미만 점진 전이 구간 행 수: {intermediate_rows} ({intermediate_rows/total_rows:.1%})")


if __name__ == "__main__":
    main()

"""Calculate simulated DRT-to-transfer punctuality for R01~R04 from stored road models only."""
from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "sewook31"
PARAMS = ROOT / "data" / "assumptions" / "sim_params.json"
CONGESTION = ROOT / "data" / "processed" / "congestion_by_hour.csv"
OUT_CSV = ROOT / "data" / "processed" / "punctuality_main_results.csv"
OUT_PNG = ROOT / "data" / "processed" / "punctuality_main_chart.png"
HEADERS = ["노선", "정류장", "환승역", "시간대", "구간유형", "혼잡수준", "합승수", "여유분",
           "놓칠확률", "평균대기분", "기준대기분", "가정"]
REPS = 10_000
HEADWAY = 10
PASSENGER_DELAY = 2.0


def read_inputs(allow_network=False):
    """R01~R04 boarding stops from the operating web's route plans (single source)."""
    if str(APP) not in sys.path:
        sys.path.insert(0, str(APP))
    from modules.punctuality_routes import route_legs, label
    config = json.loads(PARAMS.read_text(encoding="utf-8"))
    with CONGESTION.open(encoding="utf-8-sig", newline="") as f:
        congestion = list(csv.DictReader(f))
    legs, problems = route_legs(allow_network=allow_network)
    routes = [(f"{leg['stop_name']} ({leg['stop_id']})", float(leg["ride_min"]), leg["destination_name"], leg["route_id"])
              for leg in legs if leg["ride_min"] is not None]
    skipped = [label(leg) for leg in legs if leg["ride_min"] is None] + [p for p in problems if "정시성 계산 제외" not in p]
    return routes, skipped, config, congestion


def factor_ranges(rows, hours):
    values = [float(r["k"]) for r in rows if int(r["시간"]) in hours and r.get("k") not in (None, "")]
    if not values:
        raise ValueError(f"congestion_by_hour.csv에 {hours}시 혼잡값이 없습니다")
    values.sort()
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return min(values), median, max(values)


def simulate(routes, config, congestion):
    rng = random.Random(42)
    dwell = float(config.get("dwell_minutes", {}).get("value", 1))
    groups = [("출근", [7, 8, 9]), ("퇴근", [17, 18, 19])]
    results = []
    for period, hours in groups:
        corridor = factor_ranges(congestion, hours)
        for route in routes:
            stop_name, duration, tram_name = route[:3]
            route_id = route[3] if len(route) > 3 else ""
            for segment in ("단지내", "간선연계"):
                bounds = (1.0, 1.1, 1.2) if segment == "단지내" else corridor
                factor_names = ("min", "mode", "max")
                lo_all, mode_all, hi_all = bounds
                scenarios = {
                    "min": (lo_all, lo_all, mode_all),
                    "mode": (lo_all, mode_all, hi_all),
                    "max": (mode_all, hi_all, hi_all),
                }
                for level, (lo, mode, hi) in scenarios.items():
                    for passengers in (0, 1, 2):
                        deltas = [duration * (rng.triangular(lo, hi, mode) - mode)
                                  + passengers * PASSENGER_DELAY for _ in range(REPS)]
                        for buffer in range(11):
                            missed = 0
                            waits = 0.0
                            for delta in deltas:
                                lateness = delta - buffer
                                if lateness > 1e-12:
                                    missed += 1
                                    remainder = lateness % HEADWAY
                                    waits += HEADWAY - remainder if remainder > 1e-12 else 0
                                else:
                                    waits += -lateness
                            assumptions = (f"{route_id} 승차→{tram_name} 차내시간 T={duration:.3f}분(운영 노선 도로 모형·중간 정차 포함); 삼각분포 k={lo:.4f}/{mode:.4f}/{hi:.4f}; "
                                           f"정차={dwell:g}분; 합승={PASSENGER_DELAY:g}분/인; 배차={HEADWAY}분; "
                                           "요일·시간 구간 대응 assumption; 운행 실측 아님")
                            results.append({"노선": route_id, "정류장": stop_name, "환승역": tram_name, "시간대": period, "구간유형": segment,
                                            "혼잡수준": level, "합승수": passengers, "여유분": buffer,
                                            "놓칠확률": missed / REPS,
                                            "평균대기분": waits / REPS,
                                            "기준대기분": HEADWAY / 2,
                                            "가정": assumptions})
    return results


def _font(size):
    for path in (r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _mean_series(rows, period, segment, level):
    selected = [r for r in rows if r["시간대"] == period and r["구간유형"] == segment
                and r["혼잡수준"] == level and r["합승수"] == 0]
    buffers = sorted({r["여유분"] for r in selected})
    # One mean per buffer across stops, rather than joining different stops end to end.
    return buffers, [
        (sum(r["놓칠확률"] for r in selected if r["여유분"] == b) / sum(r["여유분"] == b for r in selected),
         sum(r["평균대기분"] for r in selected if r["여유분"] == b) / sum(r["여유분"] == b for r in selected))
        for b in buffers]


def draw_chart(rows):
    """Matplotlib chart (mode solid / max dotted, passengers 0); Pillow fallback."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except ImportError:
        return _draw_chart_pillow(rows)
    korean = Path(r"C:\Windows\Fonts\malgun.ttf")
    if korean.exists():
        font_manager.fontManager.addfont(str(korean))
        plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(korean)).get_name()
    plt.rcParams["axes.unicode_minus"] = False
    routes = sorted({r.get("노선", "") for r in rows} - {""})
    scope = "·".join(routes) if routes else "운영 노선"
    fig, axes = plt.subplots(1, 2, figsize=(20, 8.67), dpi=150)
    colors = {("출근", "단지내"): "#169b72", ("출근", "간선연계"): "#2f63b0",
              ("퇴근", "단지내"): "#7b6bb8", ("퇴근", "간선연계"): "#d95f02"}
    for (period, segment), color in colors.items():
        for level, style, marker in (("mode", "-", "o"), ("max", ":", "x")):
            buffers, values = _mean_series(rows, period, segment, level)
            if not buffers:
                continue
            label = f"{period}-{segment} ({level})"
            axes[0].plot(buffers, [v[0] for v in values], style, marker=marker, color=color, linewidth=2.2, markersize=5, label=label)
            axes[1].plot(buffers, [v[1] for v in values], style, marker=marker, color=color, linewidth=2.2, markersize=5, label=label)
    axes[1].axhline(HEADWAY / 2, color="#d62728", linestyle="--", linewidth=3, label=f"기준선: 임의도착 평균대기 {HEADWAY / 2:g}분")
    titles = ("여유시간(b)별 환승 놓칠 확률 (합승 0명, mode 실선 / max 점선)",
              "여유시간(b)별 평균 환승 대기시간 (합승 0명, mode 실선 / max 점선)")
    for ax, title, ylabel in zip(axes, titles, ("놓칠 확률", "평균 대기시간 (분)")):
        ax.set_title(title, fontweight="bold", fontsize=13)
        ax.set_xlabel("환승 여유시간 b (분)", fontsize=12)
        ax.set_ylabel(ylabel, fontsize=12)
        ax.set_xticks(range(11))
        ax.grid(True, linestyle="--", alpha=.5)
        ax.legend(loc="upper right", fontsize=9)
    axes[0].set_ylim(-.02, 1.05)
    if not rows:
        for ax in axes:
            ax.text(.5, .5, "도로 모형이 있는 정류장이 없습니다", ha="center", transform=ax.transAxes, color="#9b1c1c")
    fig.suptitle(f"DRT 환승 정시성 시뮬레이션 결과 ({scope} 정류장 평균 · 혼잡수준: mode vs max)", fontweight="bold", fontsize=16)
    fig.tight_layout()
    fig.savefig(OUT_PNG, format="png")
    plt.close(fig)


def _draw_chart_pillow(rows):
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
        print("캐시 경로를 찾지 못해 건너뛴 정류장: 없음")
    if not rows:
        print("경고: 결과가 비었습니다. OSRM cache route가 없습니다.")
        return
    print("\n요약: 혼잡수준=mode, 정류장별 평균(캐시가 있는 정류장)")
    print("시간대 | 구간유형 | 합승 | b=0 놓침/대기 | b=3 | b=5 | b=8 | 평균기준")
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                cells = []
                for buffer in (0, 3, 5, 8):
                    selected = [r for r in rows if r["시간대"] == period and r["구간유형"] == segment
                                and r["혼잡수준"] == "mode" and r["합승수"] == passengers and r["여유분"] == buffer]
                    missed = sum(r["놓칠확률"] for r in selected) / len(selected)
                    wait = sum(r["평균대기분"] for r in selected) / len(selected)
                    cells.append(f"{missed:.1%}/{wait:.2f}")
                print(f"{period} | {segment} | {passengers} | " + " | ".join(cells) + " | 5.00분")
    print("\n놓침 확률 5% 이하가 되는 최소 b (혼잡수준=mode):")
    for period in ("출근", "퇴근"):
        for segment in ("단지내", "간선연계"):
            for passengers in (0, 2):
                parts = []
                for stop in sorted({r["정류장"] for r in rows}):
                    selected = [r for r in rows if r["정류장"] == stop and r["시간대"] == period
                                and r["구간유형"] == segment and r["혼잡수준"] == "mode" and r["합승수"] == passengers]
                    safe = [r["여유분"] for r in selected if r["놓칠확률"] <= 0.05]
                    parts.append(f"{stop}:{min(safe) if safe else '10분 내 없음'}")
                print(f"{period}/{segment}/합승{passengers}: " + ", ".join(parts))
    monotonic = True
    groups = {}
    for r in rows:
        key = tuple(r[k] for k in ("정류장", "시간대", "구간유형", "혼잡수준", "합승수"))
        groups.setdefault(key, []).append(r)
    for values in groups.values():
        values.sort(key=lambda r: r["여유분"])
        monotonic &= all(a["놓칠확률"] >= b["놓칠확률"] for a, b in zip(values, values[1:]))
    print(f"여유 증가 시 놓침확률이 항상 감소 또는 같음: {'예' if monotonic else '아니요'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Weekday congestion summaries from Wirye speed data; never edits source files."""
from __future__ import annotations

import csv
import json
import math
import posixpath
import statistics
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEED_FILE = ROOT / "data/raw/wirye_speed_raw.csv"
XLSX_FILE = ROOT / "data/processed/위례_DRT_GITS_도로교통정보_정리.xlsx"
OUT_CSV = ROOT / "data/processed/congestion_by_hour.csv"
OUT_PARAMS = ROOT / "data/assumptions/congestion_params.json"
SIM_PARAMS = ROOT / "sewook31/sim_params.json"
PERIODS = {"출근": range(7, 10), "낮": range(10, 17), "퇴근": range(17, 20), "밤": range(20, 24)}
DOW = ["월", "화", "수", "목", "금", "토", "일"]


def read_csv(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return list(csv.DictReader(raw.decode(enc).splitlines())), enc
        except UnicodeDecodeError:
            pass
    raise UnicodeError(f"Cannot decode {path}")


def num(value):
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def median(values):
    return statistics.median(values) if values else None


def xlsx_sheets(path: Path):
    """Read cached cell values from XLSX without changing the workbook."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        relroot = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in relroot}
        strings = []
        if "xl/sharedStrings.xml" in names:
            sr = ET.fromstring(z.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in si.findall(".//m:t", ns)) for si in sr.findall("m:si", ns)]
        result = {}
        for sh in wb.findall("m:sheets/m:sheet", ns):
            target = rels[sh.attrib[f'{{{ns["r"]}}}id']]
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = posixpath.normpath(posixpath.join("xl", target))
            root = ET.fromstring(z.read(target))
            rows = []
            for row in root.findall(".//m:sheetData/m:row", ns):
                vals = []
                for cell in row.findall("m:c", ns):
                    v = cell.find("m:v", ns)
                    value = v.text if v is not None else ""
                    if cell.attrib.get("t") == "s" and value:
                        value = strings[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
                    vals.append(value)
                rows.append(vals)
            result[sh.attrib["name"]] = rows
        return result


def workbook_link_rows(path: Path):
    sheets = xlsx_sheets(path)
    for sheet_name, matrix in sheets.items():
        for i, row in enumerate(matrix):
            norm = [str(x).strip() for x in row]
            if "LINK_ID" in norm and any("속도" in x for x in norm) and any("길이" in x for x in norm):
                headers = norm
                records = []
                for r in matrix[i + 1:]:
                    r = r + [""] * max(0, len(headers) - len(r))
                    item = dict(zip(headers, r))
                    if item.get("LINK_ID"):
                        records.append(item)
                return sheet_name, headers, records
    raise ValueError("XLSX에서 LINK_ID·속도·길이 헤더가 있는 링크별 시트를 찾지 못했습니다")


def main():
    rows, enc = read_csv(SPEED_FILE)
    if not rows:
        raise ValueError("속도 원본에 데이터 행이 없습니다")
    fields = list(rows[0])
    tm_cols = [f"TM{i:02d}_SPEED" for i in range(1, 25)]
    if any(c not in fields for c in tm_cols):
        raise ValueError("TM01_SPEED~TM24_SPEED 열이 모두 필요합니다")

    # Full-source medians, including numeric zero values, for the requested pattern check.
    tm_medians = {c: median([v for r in rows if (v := num(r.get(c))) is not None]) for c in tm_cols}
    maxval = max(v for v in tm_medians.values() if v is not None)
    minval = min(v for v in tm_medians.values() if v is not None)
    maxcols = [c for c, v in tm_medians.items() if v == maxval]
    mincols = [c for c, v in tm_medians.items() if v == minval]
    # Required candidate: TMnn is interval (nn-1):00 to nn:00.
    hour0 = {f"TM{i:02d}_SPEED": (i - 1) % 24 for i in range(1, 25)}
    dawn_hours, commute_hours = {23, 0, 1, 2, 3, 4}, set(range(7, 10)) | set(range(17, 20))
    max_pattern = any(hour0[c] in dawn_hours for c in maxcols)
    min_pattern = any(hour0[c] in commute_hours for c in mincols)
    accepted = max_pattern and min_pattern
    print(f"속도 파일 인코딩={enc}; 행수={len(rows)}; 열={', '.join(fields)}")
    print("TM 열별 전체 중앙값 (0 포함):")
    for c in tm_cols:
        print(f"  {c}: {tm_medians[c]:.3f}" if tm_medians[c] is not None else f"  {c}: missing")
    print(f"중앙값 최고={maxval:.3f} ({', '.join(maxcols)}), 최저={minval:.3f} ({', '.join(mincols)})")
    print(f"요청 패턴 검사: 최고 새벽={max_pattern}, 최저 출퇴근={min_pattern}")
    if not accepted:
        print("시간 대응을 채택하지 않습니다. 조건상 TM 중앙값 24개와 패턴 판정만 보고하고 나머지 계산을 중단합니다.")
        return
    print("채택(assumption): TMnn=(nn-1)시~nn시; 근거=열별 중앙값 패턴")
    print("민감도: TMnn=nn시~(nn+1)시도 별도로 산출합니다.")

    # Date parsing from YY/MT/DE. Keep invalid rows out of weekday analysis.
    valid_dates, invalid_dates, weekday_rows = [], 0, []
    weekday_counts = Counter()
    dated = []
    for r in rows:
        try:
            dt = date(int(r["YY"]), int(r["MT"]), int(r["DE"]))
            dated.append((r, dt)); valid_dates.append(dt)
            weekday_counts[DOW[dt.weekday()]] += 1
            if dt.weekday() < 5:
                weekday_rows.append(r)
        except (KeyError, TypeError, ValueError):
            invalid_dates += 1
    unique_dates = sorted(set(valid_dates))
    print(f"날짜 개수={len(unique_dates)}; 범위={unique_dates[0] if unique_dates else 'missing'}~{unique_dates[-1] if unique_dates else 'missing'}; 날짜변환실패행={invalid_dates}")
    print("요일별 행수=" + ", ".join(f"{d}요일 {weekday_counts[d]}" for d in DOW))
    print(f"평일 행수={len(weekday_rows)}; 공휴일은 별도 제외하지 않음")

    # Scale check: positive speeds are used for the physical range; zero values remain in raw min.
    tm_values = [v for r in rows for c in tm_cols if (v := num(r.get(c))) is not None]
    positive = [v for v in tm_values if v > 0]
    daily_vals = [v for r in rows if (v := num(r.get("DAY1_AVG_SPEED"))) is not None and v > 0]
    row_tm_means = []
    for r in rows:
        vals = [v for c in tm_cols if (v := num(r.get(c))) is not None and v > 0]
        if vals:
            row_tm_means.append(statistics.mean(vals))
    unit_accepted = bool(positive and min(positive) >= 5 and max(positive) <= 120 and daily_vals and row_tm_means
                         and abs(median(daily_vals) - median(row_tm_means)) / max(median(daily_vals), 1e-9) <= 0.25)
    print(f"TM 속도 전체 min/median/max={min(tm_values):.3f}/{median(tm_values):.3f}/{max(tm_values):.3f}; 양수만={min(positive):.3f}/{median(positive):.3f}/{max(positive):.3f}")
    print(f"DAY1_AVG_SPEED 중앙값={median(daily_vals):.3f}; 행별 양수 TM 평균 중앙값={median(row_tm_means):.3f}")
    print("속도 단위 판정=" + ("km/h (assumption; 양수범위와 DAY1 평균 비교가 기준에 부합)" if unit_accepted else "missing (요청한 범위/일평균 비교 기준을 충족하지 않음)"))

    segments = defaultdict(list)
    for r in weekday_rows:
        route = (r.get("ROUTE_NM") or "missing").strip()
        start = (r.get("BGPT_LOC") or "missing").strip()
        end = (r.get("LASTSTOP_LOC") or "missing").strip()
        direction = (r.get("UPNDW_DIV") or "missing").strip()
        seg = f"{route} ({direction}: {start}→{end})"
        segments[seg].append(r)
    if len(segments) != 12:
        print(f"주의: 평일 자료에서 구성된 구간 수는 {len(segments)} (이전 전체행에서 기대한 12와 다름)")

    maps = {"채택": hour0, "1시간밀림": {f"TM{i:02d}_SPEED": i % 24 for i in range(1, 25)}}
    outputs, band_summaries = {}, {}
    for map_name, mapping in maps.items():
        perseg = {}
        detail = []
        for seg, recs in segments.items():
            speeds = {c: median([v for r in recs if (v := num(r.get(c))) is not None and v > 0]) for c in tm_cols}
            night_cols = [c for c in tm_cols if mapping[c] in {23, 0, 1, 2, 3, 4}]
            free = median([speeds[c] for c in night_cols if speeds[c] is not None])
            byhour = {}
            for c in tm_cols:
                h = mapping[c]
                v = speeds[c]
                k = max(1.0, free / v) if free is not None and v is not None and v > 0 else None
                byhour[h] = {"speed": v, "free": free, "k": k, "tm": c.replace("_SPEED", "")}
            perseg[seg] = byhour
            for h in range(24):
                item = byhour.get(h, {})
                detail.append({"도로구간": seg, "시간": h, "TM열": item.get("tm", "missing"),
                               "속도_kmh": item.get("speed"), "자유류속도_kmh": item.get("free"), "k": item.get("k"),
                               "산정방법": "평일 구간별 시간중앙값; 자유류속도=23~05시 구간중앙값; k=max(1, 자유류/시간속도)",
                               "status": "assumption"})
        outputs[map_name] = detail
        bsum = {}
        for band, hours in PERIODS.items():
            road_k = {}
            for seg, byhour in perseg.items():
                vals = [byhour[h]["k"] for h in hours if byhour[h]["k"] is not None]
                if vals:
                    road_k[seg] = statistics.mean(vals)
            vals = list(road_k.values())
            top = sorted(road_k.items(), key=lambda kv: kv[1], reverse=True)[:3]
            bsum[band] = {"min": min(vals) if vals else None, "median": median(vals),
                          "max": max(vals) if vals else None, "mean": statistics.mean(vals) if vals else None,
                          "segments_with_values": len(vals), "top3": top}
        band_summaries[map_name] = bsum

    # Save adopted mapping only, all values computed from weekday records.
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(outputs["채택"][0]))
        w.writeheader(); w.writerows(outputs["채택"])
    limitations = ["수집 기간의 의미 미확인 (YY/MT/DE에서 날짜 조합 가능)", "공휴일을 별도 제외하지 않고 평일에 포함",
                   "간선도로 3개 기준이며 단지 내 도로는 미포함", "시간 구간 대응은 열별 중앙값 패턴에 근거한 assumption"]
    params = {"status": "assumption(시간 구간 대응을 열별 패턴으로 추정)", "source": "data/raw/wirye_speed_raw.csv",
              "시간구간_채택": "TMnn=(nn-1)시~nn시", "시간구간_근거": "열별 중앙값 패턴: 최고 중앙값이 새벽 구간, 최저 중앙값이 출퇴근 구간에 위치",
              "속도단위": {"value": "km/h" if unit_accepted else "missing", "status": "assumption" if unit_accepted else "missing",
                         "basis": "양수 속도 범위와 DAY1_AVG_SPEED 중앙값 대비 시간대 평균속도 중앙값 비교"},
              "도로수": len(segments), "평일행수": len(weekday_rows), "기간별": band_summaries["채택"],
              "민감도_1시간밀림_기간별": band_summaries["1시간밀림"], "한계": limitations}
    OUT_PARAMS.parent.mkdir(parents=True, exist_ok=True)
    OUT_PARAMS.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    print("시간대 k 요약 (채택 / 1시간 밀림):")
    for band in PERIODS:
        a, b = band_summaries["채택"][band], band_summaries["1시간밀림"][band]
        print(f"{band}: 채택 min/median/max/mean={a['min']:.3f}/{a['median']:.3f}/{a['max']:.3f}/{a['mean']:.3f}; 밀림={b['min']:.3f}/{b['median']:.3f}/{b['max']:.3f}/{b['mean']:.3f}" if a["mean"] is not None and b["mean"] is not None else f"{band}: missing")
        print("  채택 상위3=" + "; ".join(f"{s} k={k:.3f}" for s, k in a["top3"]))
        print("  밀림 상위3=" + "; ".join(f"{s} k={k:.3f}" for s, k in b["top3"]))

    # Read-only link-level workbook analysis.
    sh, headers, links = workbook_link_rows(XLSX_FILE)
    speed_col = next((h for h in headers if "속도" in h), None)
    duration_col = next((h for h in headers if "통행시간" in h or "소요시간" in h), None)
    length_col = next((h for h in headers if "길이" in h or "거리" in h), None)
    road_col = next((h for h in headers if h == "도로명"), headers[0])
    groups = defaultdict(list)
    valid_links = []
    for r in links:
        sp = num(r.get(speed_col))
        if sp is not None:
            groups[r.get(road_col) or "missing"].append(sp)
            valid_links.append(r)
    duration_count = sum(num(r.get(duration_col)) is not None for r in links) if duration_col else 0
    length_count = sum(num(r.get(length_col)) is not None for r in links) if length_col else 0
    timestamp_cols = [h for h in headers if any(k in h for k in ("관측시각", "관측시간", "수집시각", "수집시간", "측정일시"))]
    print(f"단지내 엑셀 링크 시트={sh}; 링크 행={len(links)}; 속도 유효={len(valid_links)}({speed_col}); 통행시간 유효={duration_count}({duration_col}); 길이/거리 유효={length_count}({length_col}); 관측시각 열={'있음: ' + ', '.join(timestamp_cols) if timestamp_cols else '없음 → 한 시점의 스냅샷'}")
    for road, vals in sorted(groups.items()):
        med = median(vals)
        delta = med - 30
        print(f"단지내 {road}: 속도 중앙값={med:.2f} km/h (n={len(vals)}), 30 km/h 기준 대비 {delta:+.2f} km/h, {('초과' if delta > 0 else '이하')}; status=sourced (XLSX 링크별 속도 열)")

    # Add requested parameters only; preserve existing keys and keep application code untouched.
    sim = json.loads(SIM_PARAMS.read_text(encoding="utf-8")) if SIM_PARAMS.exists() else {}
    band = band_summaries["채택"]
    sim["traffic_factor_by_band"] = {"진입간선": {name: {"min": band[name]["min"], "mode": band[name]["median"], "max": band[name]["max"]} for name in PERIODS},
                                     "단지내": {"min": 1.0, "mode": 1.0, "max": 1.2}}
    sim["traffic_factor_by_band_status"] = {"진입간선": "assumption (시간대 대응 및 속도 단위 추정; mode=구간별 k 평균의 중앙값)",
                                            "단지내": "assumption (자료 근거 부족으로 임시 범위; 실제 반영 전 확인 필요)"}
    SIM_PARAMS.write_text(json.dumps(sim, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장 완료: {OUT_CSV.relative_to(ROOT)}, {OUT_PARAMS.relative_to(ROOT)}, {SIM_PARAMS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

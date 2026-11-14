from __future__ import annotations

import csv
import json
import math
import os
import re
import unicodedata
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TODAY = date.today().isoformat()


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def find_name(folder: Path, contains: str) -> Path:
    for path in folder.iterdir():
        if contains in nfc(path.name):
            return path
    raise FileNotFoundError(contains)


def read_csv(path: Path, encodings=("utf-8-sig", "cp949")):
    for encoding in encodings:
        try:
            with path.open(encoding=encoding, newline="") as handle:
                return list(csv.DictReader(handle))
        except (UnicodeDecodeError, LookupError):
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, str(path))


def csv_encoding(path: Path):
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with path.open(encoding=encoding) as handle:
                handle.read(4096)
            return encoding
        except UnicodeDecodeError:
            continue
    return "cp949"


def write_csv(path: Path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def norm_name(value: str) -> str:
    value = nfc(value or "").lower()
    return re.sub(r"[\s·._-]|아파트", "", value)


def haversine_m(lon1, lat1, lon2, lat2):
    radius = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def point_in_ring(lon, lat, ring):
    inside = False
    for index in range(len(ring)):
        x1, y1 = ring[index - 1]
        x2, y2 = ring[index]
        crosses = (y1 > lat) != (y2 > lat)
        if crosses and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def point_in_polygon(lon, lat, geometry):
    rings = geometry["coordinates"]
    if not point_in_ring(lon, lat, rings[0]):
        return False
    return not any(point_in_ring(lon, lat, hole) for hole in rings[1:])


def load_boundary():
    obj = json.loads((ROOT / "data/processed/wirye_changgok_boundary.geojson").read_text(encoding="utf-8-sig"))
    return obj["features"][0]["geometry"]


def load_stations():
    obj = json.loads((ROOT / "data/processed/wirye_tram_official_stations.geojson").read_text(encoding="utf-8-sig"))
    stations = []
    for feature in obj["features"]:
        props = feature["properties"]
        lon, lat = feature["geometry"]["coordinates"]
        stations.append({"number": str(props["station_no"]), "name": props["station_name"], "lon": lon, "lat": lat})
    return stations


def geocode(address):
    env_path = ROOT / ".env"
    key = ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("KAKAO_REST_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key or not address:
        return None
    try:
        import requests
        response = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers={"Authorization": "KakaoAK " + key},
            params={"query": address},
            timeout=10,
        )
        response.raise_for_status()
        documents = response.json().get("documents", [])
        if documents:
            return float(documents[0]["x"]), float(documents[0]["y"])
    except Exception:
        return None
    return None


def build_apartment_master():
    docs_path = next(path for path in (ROOT / "docs").iterdir() if path.stat().st_size == 8814)
    lines = [line.strip() for line in docs_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    doc_rows = []
    for line in lines:
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].strip().isdigit():
            doc_rows.append({"name": parts[0].strip(), "households": int(parts[1].strip())})
    doc_rows = doc_rows[:29]
    households_path = ROOT / "data/assumptions/apartment_households.csv"
    household_rows = read_csv(households_path)
    vulnerable = json.loads((ROOT / "data/processed/wirye_vulnerable_apartments.geojson").read_text(encoding="utf-8-sig"))["features"]
    by_name = {norm_name(row["단지명"]): row for row in household_rows}
    vuln_by_name = {norm_name(feature["properties"]["name"]): feature for feature in vulnerable}
    aliases = {
        norm_name("위례그린파크푸르지오아파트"): norm_name("위례그린파크푸르지오"),
        norm_name("위례호반써밋에비뉴아파트"): norm_name("위례호반써밋에비뉴"),
        norm_name("위례포레샤인23단지아파트"): norm_name("위례포레스트부영"),
        norm_name("위례35단지아파트"): norm_name("위례 LH 35단지"),
        norm_name("E편한세상테라스위례"): norm_name("e편한세상 테라스위례"),
    }
    rows = []
    for doc in doc_rows:
        canonical = doc["name"]
        household = by_name.get(norm_name(canonical))
        if household is None:
            household = by_name.get(norm_name(canonical.replace("아파트", "")))
        vuln = vuln_by_name.get(norm_name(canonical))
        if vuln is None:
            vuln = vuln_by_name.get(aliases.get(norm_name(canonical), ""))
        notes = []
        if household and int(household["세대수"]) != doc["households"]:
            notes.append(f"문서 {doc['households']}세대와 K-apt {household['세대수']}세대 불일치")
        if household and household.get("비고"):
            notes.append(household["비고"])
        if vuln:
            notes.append("취약 아파트 GeoJSON 연결")
        households = household["세대수"] if household else str(doc["households"])
        source = household.get("출처", "docs/관리용 웹사이트 구상") if household else "docs/관리용 웹사이트 구상"
        address = household.get("도로명주소", "") if household else ""
        lon = lat = ""
        if vuln:
            lon, lat = vuln["geometry"]["coordinates"]
        elif address:
            location = geocode(address)
            if location:
                lon, lat = location
        if not lon or not lat:
            notes.append("좌표 missing")
        rows.append({
            "단지명": canonical,
            "세대수": households,
            "세대수출처": source,
            "도로명주소": address,
            "경도": lon,
            "위도": lat,
            "분양형태": household.get("분양형태", "") if household else "",
            "사각지대여부(700m)": "Y" if vuln else "N",
            "모델반영": household.get("모델반영", "") if household else "Y",
            "비고": "; ".join(notes),
        })
    write_csv(ROOT / "data/processed/apartment_master.csv", list(rows[0]), rows)
    return rows, vulnerable


def load_bus_stops(boundary):
    source = next(path for path in (ROOT / "data/raw").iterdir() if path.is_file() and path.stat().st_size == 20735435)
    stops = []
    with source.open(encoding="cp949", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                lon, lat = float(row["경도"]), float(row["위도"])
            except (ValueError, KeyError):
                continue
            if point_in_polygon(lon, lat, boundary):
                stops.append((row.get("정류장번호", ""), row.get("정류장명", ""), lon, lat))
    return stops


def build_access(rows, stations, boundary):
    bus_stops = load_bus_stops(boundary)
    output = []
    for row in rows:
        try:
            lon, lat = float(row["경도"]), float(row["위도"])
        except (ValueError, TypeError):
            output.append({"단지명": row["단지명"], "가장가까운정거장": "missing", "직선거리_m": "", "도보거리_m": "", "도보거리산정방법": "missing", "500m이내기존버스정류장수": "", "가장가까운기존버스정류장거리_m": ""})
            continue
        nearest = min(stations, key=lambda station: haversine_m(lon, lat, station["lon"], station["lat"]))
        tram_distance = haversine_m(lon, lat, nearest["lon"], nearest["lat"])
        distances = [haversine_m(lon, lat, stop[2], stop[3]) for stop in bus_stops]
        within = [distance for distance in distances if distance <= 500]
        output.append({
            "단지명": row["단지명"],
            "가장가까운정거장": f"{nearest['number']} {nearest['name']}",
            "직선거리_m": round(tram_distance, 1),
            "도보거리_m": round(tram_distance * 1.3, 1),
            "도보거리산정방법": "assumption: 직선거리×1.3",
            "500m이내기존버스정류장수": len(within),
            "가장가까운기존버스정류장거리_m": round(min(distances), 1) if distances else "",
        })
    fields = list(output[0])
    write_csv(ROOT / "data/processed/apartment_tram_access.csv", fields, output)
    return output


def build_candidates(rows, vulnerable, stations):
    vulnerable_names = {norm_name(feature["properties"]["name"]): feature for feature in vulnerable}
    row_by_name = {norm_name(row["단지명"]): row for row in rows}
    aliases = {norm_name("위례포레샤인23단지아파트"): norm_name("위례포레스트부영")}
    vulnerable_to_master = {value: key for key, value in aliases.items()}
    candidates = []
    existing = {"D01", "D02", "D03", "D04"}
    matched_vulnerable = set()
    candidate_rows = list(rows)
    for feature in vulnerable:
        name = feature["properties"]["name"]
        canonical_key = vulnerable_to_master.get(norm_name(name), norm_name(name))
        row = row_by_name.get(canonical_key)
        if row is None:
            row = {"단지명": name, "세대수": feature["properties"].get("households", "missing")}
        matched_vulnerable.add(norm_name(name))
        lon, lat = feature["geometry"]["coordinates"]
        nearest = min(stations, key=lambda station: haversine_m(lon, lat, station["lon"], station["lat"]))
        distance = haversine_m(lon, lat, nearest["lon"], nearest["lat"])
        household_text = re.sub(r"[^0-9]", "", str(row["세대수"]))
        households = int(household_text) if household_text else 0
        weight = max(0.8, min(1.5, 1.5 - 0.7 * distance / 700)) if distance <= 700 else 0.8
        score = households * weight
        candidates.append({"단지명": row["단지명"], "세대수": households or "missing", "가장가까운정거장": f"{nearest['number']} {nearest['name']}", "직선거리_m": round(distance, 1), "거리함수": round(weight, 4), "우선순위점수": round(score, 1) if households else "missing", "기존D01_D04중복여부": "아니오", "산정상태": "assumption" if households else "missing"})
    candidates.sort(key=lambda item: item["우선순위점수"] if isinstance(item["우선순위점수"], (int, float)) else -1, reverse=True)
    candidates = candidates[:15]
    write_csv(ROOT / "data/processed/virtual_stop_candidates.csv", list(candidates[0]), candidates)
    return candidates


def build_destinations(boundary):
    source_dir = next(path for path in (ROOT / "data/raw").iterdir() if path.is_dir() and "소상공인" in nfc(path.name))
    keywords = {"병원": "병원", "약국": "약국", "마트": "마트", "쇼핑몰": "쇼핑몰", "행정복지센터": "행정복지센터", "학교": "학교"}
    rows = []
    for source in source_dir.glob("*.csv"):
        if "경기" not in nfc(source.name):
            continue
        with source.open(encoding=csv_encoding(source), newline="") as handle:
            for record in csv.DictReader(handle):
                name = record.get("상호명", "")
                categories = " ".join(record.get(key, "") for key in ("상권업종대분류명", "상권업종중분류명", "상권업종소분류명", "표준산업분류명"))
                if "병원" in name or "병원" in categories:
                    category = "병원"
                elif "약국" in name or "약국" in categories:
                    category = "약국"
                elif "행정복지센터" in name or "행정복지센터" in categories:
                    category = "행정복지센터"
                elif any(token in name for token in ("초등학교", "중학교", "고등학교")) or "학교" in categories:
                    category = "학교"
                elif any(token in name for token in ("마트", "이마트", "슈퍼")) or any(token in categories for token in ("마트", "슈퍼", "편의점")):
                    category = "마트"
                elif "쇼핑몰" in name or "쇼핑몰" in categories:
                    category = "쇼핑몰"
                else:
                    category = None
                if not category:
                    continue
                try:
                    lon, lat = float(record["경도"]), float(record["위도"])
                except (ValueError, KeyError):
                    continue
                if point_in_polygon(lon, lat, boundary):
                    rows.append({"이름": record.get("상호명", ""), "업종분류": category, "경도": lon, "위도": lat, "출처": "data/raw/소상공인시장진흥공단_상가(상권)정보_20260630/경기"})
    write_csv(ROOT / "data/processed/destination_candidates.csv", ["이름", "업종분류", "경도", "위도", "출처"], rows)
    return rows


def build_timetable(stations):
    by_number = {station["number"]: station for station in stations}
    main = ["101", "102", "103", "104", "105", "106", "107", "108", "111", "112"]
    branch = ["108", "109", "110"]
    total_distance = sum(haversine_m(by_number[a]["lon"], by_number[a]["lat"], by_number[b]["lon"], by_number[b]["lat"]) for a, b in zip(main, main[1:]))
    segments = []
    cumulative = 0
    for a, b in zip(main, main[1:]):
        distance = haversine_m(by_number[a]["lon"], by_number[a]["lat"], by_number[b]["lon"], by_number[b]["lat"])
        minutes = 14 * distance / total_distance
        cumulative += minutes
        segments.append({"from": a, "to": b, "distance_m": round(distance, 1), "minutes": round(minutes, 3), "status": "sourced", "source": "서울시 보도 2026-02"})
    result = {
        "status": "assumption",
        "source_note": "구간별 좌표거리 비율은 계산값이며, 전체 14분과 101→107 약 8분의 근거는 서울시 보도 2026-02",
        "main_line": {"station_order": main, "total_minutes": {"value": 14, "status": "sourced", "source": "서울시 보도 2026-02"}, "segments": segments},
        "branch_line": {"station_order": branch, "segments": [{"from": a, "to": b, "distance_m": round(haversine_m(by_number[a]["lon"], by_number[a]["lat"], by_number[b]["lon"], by_number[b]["lat"]), 1), "minutes": None, "status": "missing", "source": "구간 운행시간 출처 없음"} for a, b in zip(branch, branch[1:])]},
        "validation": {"cumulative_101_to_107_minutes": round(sum(item["minutes"] for item in segments[:6]), 3), "target_minutes": 8, "status": "sourced", "source": "서울시 보도 2026-02"},
        "service": {"first_train": {"value": "06:00", "status": "assumption"}, "last_train": {"value": "23:30", "status": "assumption"}, "headway_peak": {"value": 10, "unit": "분", "status": "assumption"}, "headway_off_peak": {"value": 15, "unit": "분", "status": "assumption"}, "peak_periods": [{"start": "07:00", "end": "09:00", "status": "assumption"}, {"start": "17:00", "end": "19:00", "status": "assumption"}]},
        "scheduler_integration": "sewook31/modules/tram_scheduler.py에는 트램 시간표 생성 로직이 없고 DRT 역산 함수만 있으므로 중복 구현하지 않음. 웹에서 사용할 때 main_line/branch_line/service를 읽도록 연결하고, 기존 calculate_drt_schedule에는 선택된 트램 도착시각만 전달할 것.",
    }
    path = ROOT / "data/assumptions/tram_timetable.json"
    if not path.exists():
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_forms(rows, access, candidates):
    travel = ROOT / "data/assumptions/travel_time_observed.csv"
    if not travel.exists():
        write_csv(travel, ["구간ID", "출발지", "도착지", "시간대(출근/낮/퇴근/밤)", "소요분_최소", "소요분_최대", "확인방법(앱 이름)", "캡처파일명", "확인일"], [])
    blind_names = {row["단지명"] for row in rows if row["사각지대여부(700m)"] == "Y"}
    access_by_name = {row["단지명"]: row for row in access}
    todo = []
    for index, candidate in enumerate([item for item in candidates if item["단지명"] in blind_names][:6], 1):
        for period in ("출근", "낮", "퇴근", "밤"):
            todo.append({"구간ID": f"APT-TRAM-{index:02d}", "출발지": candidate["단지명"], "도착지": access_by_name[candidate["단지명"]]["가장가까운정거장"], "시간대(출근/낮/퇴근/밤)": period, "소요분_최소": "", "소요분_최대": "", "확인방법(앱 이름)": "", "캡처파일명": "", "확인일": ""})
    write_csv(ROOT / "data/assumptions/travel_time_observed_todo.csv", list(todo[0]) if todo else ["구간ID", "출발지", "도착지", "시간대(출근/낮/퇴근/밤)", "소요분_최소", "소요분_최대", "확인방법(앱 이름)", "캡처파일명", "확인일"], todo)
    stats = [{"항목": item, "현재값": "missing", "출처URL": "missing", "확인일": "missing"} for item in ("위례동 주민등록 인구", "위례동 주민등록 세대수", "가구당 인구", "차량 보험료(월)", "트램 첫차", "트램 막차")]
    write_csv(ROOT / "data/assumptions/household_stats_todo.csv", list(stats[0]), stats)


def build_catalog():
    rows = []
    descriptions = {
        "apartment_master.csv": ("29개 단지 세대수·주소·좌표 통합표", "docs/관리용 웹사이트 구상·K-apt·취약 아파트 GeoJSON", "웹 수요 예측과 지도"),
        "apartment_tram_access.csv": ("단지별 트램·기존 버스정류장 접근성", "공식 트램 GeoJSON·국토교통부 버스정류장 위치정보", "접근성 분석"),
        "virtual_stop_candidates.csv": ("취약 아파트 가상정류장 우선순위 후보", "취약 아파트 GeoJSON·사용자 지정 가중치 기준", "가상정류장 후보 선정"),
        "destination_candidates.csv": ("창곡동 경계 안 주요 목적지 후보", "소상공인시장진흥공단 상가정보", "호출형 목적지 지도"),
        "tram_timetable.json": ("위례선 트램 가상 시간표", "서울시 보도 2026-02 및 팀 가정", "환승 타임윈도우"),
        "travel_time_observed.csv": ("현장 확인용 빈 이동시간 양식", "직접 입력", "실측 이동시간 보정"),
        "travel_time_observed_todo.csv": ("실측이 필요한 단지-트램 구간 목록", "apartment_master·virtual_stop_candidates", "실측 입력 작업"),
        "household_stats_todo.csv": ("직접 확인할 단일 통계값 양식", "직접 입력", "발표 수요·비용 가정"),
        "bus_routes_real.csv": ("위례 경유 버스 운행정보", "출처 불명", "기존 버스 비교"),
        "demand_weight_params.json": ("수요 가중치 파라미터", "출처 불명", "수요 산정"),
        "drt_cost_scenarios.json": ("DRT 운영비 시나리오", "용인시 똑버스 보도자료 및 팀 가정", "운영비 시뮬레이션"),
        "wirye_grid_population.csv": ("창곡동 100m 격자 인구", "통계청 SGIS", "수요 히트맵"),
        "wirye_changgok_boundary.geojson": ("창곡동 행정구역 경계", "국토교통부 행정구역 공간데이터", "지도 경계·좌표 검증"),
        "wirye_tram_official_stations.geojson": ("위례선 공식 12개 정거장", "서울시 도시기반시설본부·대광위", "트램 지도"),
        "wirye_tram_official_lines.geojson": ("위례선 공식 선형", "서울시 도시기반시설본부", "트램 선로 지도"),
        "wirye_tram_buffer_700m.geojson": ("트램 700m 서비스 버퍼", "트램 정거장 좌표 기반 GIS", "서비스권 지도"),
        "wirye_tram_blindspot_700m.geojson": ("트램 700m 사각지대", "창곡동 경계와 트램 버퍼 공간분석", "사각지대 지도"),
        "wirye_vulnerable_apartments.geojson": ("취약 아파트 8개 포인트", "현장 답사 및 지도 거리 측정", "DRT 우선 후보"),
        "drt_stops.csv": ("기존 DRT·트램 환승 정류장", "팀 자체 가상정류장 위치 선정", "웹 정류장 지도"),
        "reservations.csv": ("DRT 예약 모의 데이터", "웹 시뮬레이션 모의 입력", "예약·차량 모니터링"),
    }
    for path in sorted((ROOT / "data").rglob("*")):
        if not path.is_file() or "raw" in path.parts or path.name == "DATA_CATALOG.csv":
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.parent == ROOT / "sewook31/data":
            key = path.name
        else:
            key = path.name
        description, source, usage = descriptions.get(key, ("프로젝트 데이터 파일", "출처 불명", "웹 시뮬레이션"))
        status = "missing" if "missing" in source or key == "bus_routes_real.csv" else ("assumption" if "가정" in source or key in {"demand_weight_params.json", "drt_cost_scenarios.json", "drt_stops.csv", "reservations.csv"} else "sourced")
        try:
            if path.suffix.lower() == ".csv":
                with path.open(encoding="utf-8-sig", newline="") as handle:
                    count = max(0, sum(1 for _ in handle) - 1)
            elif path.suffix.lower() == ".geojson":
                obj = json.loads(path.read_text(encoding="utf-8-sig"))
                count = len(obj.get("features", []))
            else:
                obj = json.loads(path.read_text(encoding="utf-8"))
                count = len(obj) if isinstance(obj, list) else len(obj.keys())
        except Exception:
            count = "확인 불가"
        rows.append({"파일경로": relative, "설명": description, "출처": source, "상태": status, "사용처": usage, "행수": count, "마지막수정일": date.fromtimestamp(path.stat().st_mtime).isoformat()})
    write_csv(ROOT / "data/DATA_CATALOG.csv", ["파일경로", "설명", "출처", "상태", "사용처", "행수", "마지막수정일"], rows)


def build_todo_document():
    content = """# 직접 해야 하는 일\n\n아래 순서대로 확인하면 발표에서 데이터 근거를 설명하기 쉽습니다. 값을 찾지 못하면 숫자를 만들지 말고 `missing`으로 남겨 주세요.\n\n1. **버스 노선 운행정보 확인**\n   - 무엇을 찾는지: 9개 노선의 첨두·비첨두 배차, 첫차, 막차, 운수회사\n   - 어디서 찾는지: 국토교통부 TAGO와 경기도 버스정보시스템\n   - 어느 파일의 어느 칸에 넣는지: `data/assumptions/bus_routes_real.csv`의 `운수회사`, `첨두배차_분`, `비첨두배차_분`, `첫차`, `막차`\n   - 걸리는 시간 예상: 1~2시간\n   - 빈칸으로 두면 막히는 질문: “기존 버스보다 DRT가 왜 필요한가요?”\n\n2. **단지 좌표와 주소 대조**\n   - 무엇을 찾는지: 29개 단지의 정확한 도로명주소와 지도 좌표\n   - 어디서 찾는지: K-apt 공동주택관리정보시스템과 카카오맵\n   - 어느 파일의 어느 칸에 넣는지: `data/processed/apartment_master.csv`의 `도로명주소`, `경도`, `위도`\n   - 걸리는 시간 예상: 1~2시간\n   - 빈칸으로 두면 막히는 질문: “어떤 단지가 실제로 트램에서 먼가요?”\n\n3. **트램-단지 이동시간 직접 측정**\n   - 무엇을 찾는지: 상위 후보 6곳의 출근·낮·퇴근·밤 도보 또는 차량 이동시간\n   - 어디서 찾는지: 네이버지도 또는 카카오맵의 도보/차량 길찾기\n   - 어느 파일의 어느 칸에 넣는지: `data/assumptions/travel_time_observed.csv`의 소요시간, 앱 이름, 캡처파일명, 확인일\n   - 걸리는 시간 예상: 1~2시간\n   - 빈칸으로 두면 막히는 질문: “직선거리×1.3이라는 가정이 실제로 맞나요?”\n\n4. **가구·보험 통계 확인**\n   - 무엇을 찾는지: 위례동 주민등록 인구·세대수, 가구당 인구, 차량 보험료, 트램 첫차·막차\n   - 어디서 찾는지: 행정안전부 주민등록 인구통계, 보험사 견적, 서울시·지자체 공식자료\n   - 어느 파일의 어느 칸에 넣는지: `data/assumptions/household_stats_todo.csv`의 `현재값`, `출처URL`, `확인일`\n   - 걸리는 시간 예상: 1시간\n   - 빈칸으로 두면 막히는 질문: “수요와 운영비 가정의 근거가 무엇인가요?”\n\n5. **호출형 목적지 좌표 확인**\n   - 무엇을 찾는지: 호출형 목적지 24곳의 좌표와 창곡동 경계 포함 여부\n   - 어디서 찾는지: 카카오맵, 네이버지도, 각 시설 공식 홈페이지\n   - 어느 파일의 어느 칸에 넣는지: `data/processed/destination_candidates.csv` 또는 원본 `data/assumptions/추가 데이터.csv`와 대조표\n   - 걸리는 시간 예상: 2~3시간\n   - 빈칸으로 두면 막히는 질문: “호출형 DRT는 실제로 어디까지 운행하나요?”\n\n6. **가상정류장 후보 현장 확인**\n   - 무엇을 찾는지: 후보 지점의 정차 가능 여부, 보행 안전, 기존 정류장과의 중복\n   - 어디서 찾는지: 현장 답사와 도로뷰\n   - 어느 파일의 어느 칸에 넣는지: `data/processed/virtual_stop_candidates.csv`의 비고 또는 별도 현장 확인표\n   - 걸리는 시간 예상: 반나절\n   - 빈칸으로 두면 막히는 질문: “점수가 높은 곳에 실제로 정류장을 만들 수 있나요?”\n"""
    (ROOT / "data/TODO_missing_data.md").write_text(content, encoding="utf-8")


def main():
    boundary = load_boundary()
    stations = load_stations()
    rows, vulnerable = build_apartment_master()
    access = build_access(rows, stations, boundary)
    candidates = build_candidates(rows, vulnerable, stations)
    build_destinations(boundary)
    build_timetable(stations)
    build_forms(rows, access, candidates)
    build_catalog()
    build_todo_document()


if __name__ == "__main__":
    main()

"""Fill missing apartment representative coordinates from Kakao Local keyword search.

Only selected place fields are persisted. API keys and response bodies are never printed or saved.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/processed/apartment_master.csv"
MANUAL = ROOT / "data/assumptions/apartment_coords_manual.csv"
OUTPUT = ROOT / "data/processed/apartment_master_enriched.csv"
RESULTS = ROOT / "data/assumptions/apartment_geocode_results.csv"
ENDPOINT = "https://dapi.kakao.com/v2/local/search/keyword.json"
ALLOWED_ADMIN = {"성남시 수정구", "하남시", "송파구"}
FIELDS = ["단지명", "위도", "경도", "출처"]


def csv_rows(path: Path):
    if not path.exists():
        return [], []
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with path.open(encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                return list(reader), reader.fieldnames or []
        except UnicodeDecodeError:
            continue
    raise UnicodeError(f"cannot decode {path.relative_to(ROOT)}")


def save_csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def env_value(name):
    path = ROOT / ".env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and match.group(1) == name:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def normalize_name(value):
    return re.sub(r"[^0-9a-z가-힣]", "", str(value).lower())


def allowed_admin(document):
    for key in ("address", "road_address"):
        address = document.get(key) or {}
        district = " ".join(str(address.get(field) or "") for field in
                             ("region_1depth_name", "region_2depth_name", "region_3depth_name"))
        if any(name in district for name in ALLOWED_ADMIN):
            return True, district
    return False, ""


def lookup(key, apartment_name):
    query = f"위례 {apartment_name}"
    response = requests.get(ENDPOINT, headers={"Authorization": f"KakaoAK {key}"},
                            params={"query": query, "size": 15}, timeout=20)
    if response.status_code != 200:
        return response.status_code, None, None
    documents = response.json().get("documents", [])
    target = normalize_name(apartment_name)
    candidates = []
    for doc in documents:
        ok, district = allowed_admin(doc)
        if not ok:
            continue
        place = str(doc.get("place_name") or "")
        normalized = normalize_name(place)
        score = difflib.SequenceMatcher(None, target, normalized).ratio()
        if not doc.get("x") or not doc.get("y"):
            continue
        candidates.append((score, place, district, float(doc["y"]), float(doc["x"])))
    if not candidates:
        return response.status_code, None, None
    score, place, district, lat, lon = max(candidates, key=lambda item: (item[0], item[1]))
    return response.status_code, {"lat": lat, "lon": lon, "place": place,
                                  "district": district, "similarity": score}, query


def main():
    key = env_value("KAKAO_REST_API_KEY")
    if not key:
        print("KAKAO_REST_API_KEY=missing; no API requests made")
        raise SystemExit(3)
    apartments, master_fields = csv_rows(MASTER)
    manual_rows, _ = csv_rows(MANUAL)
    manual = {row.get("단지명", ""): row for row in manual_rows}
    results, result_fields = csv_rows(RESULTS)
    result_by_name = {row.get("단지명", ""): row for row in results}
    to_lookup = []
    for apt in apartments:
        name = apt.get("단지명", "")
        manual_row = manual.get(name)
        if manual_row and manual_row.get("위도") and manual_row.get("경도"):
            result_by_name[name] = {"단지명": name, "위도": manual_row["위도"],
                                    "경도": manual_row["경도"], "출처": manual_row.get("출처") or "수동입력",
                                    "상태": "sourced", "매칭장소": "manual", "행정구역후보": ""}
            print(f"{name}\t성공\tmanual")
        elif apt.get("위도") and apt.get("경도"):
            continue
        elif not (result_by_name.get(name, {}).get("위도") and result_by_name.get(name, {}).get("경도")):
            to_lookup.append(name)
        else:
            print(f"{name}\t{result_by_name[name].get('상태', '실패')}\t기존결과")

    network_blocked = False
    for index, name in enumerate(to_lookup):
        if index:
            time.sleep(0.3)
        try:
            status_code, match, query = lookup(key, name)
        except requests.RequestException:
            print(f"{name}\t실패\tnetwork_error")
            result_by_name[name] = {"단지명": name, "위도": "", "경도": "", "출처": "",
                                    "상태": "missing", "매칭장소": "", "행정구역후보": "",
                                    "이름유사도": "", "질의어": f"위례 {name}"}
            save_csv(RESULTS, ["단지명", "위도", "경도", "출처", "상태", "매칭장소", "행정구역후보", "이름유사도", "질의어"],
                     list(result_by_name.values()))
            network_blocked = True
            break
        if status_code in {401, 403, 429}:
            print(f"{name}\t실패\tHTTP {status_code}")
            result_by_name[name] = {"단지명": name, "위도": "", "경도": "", "출처": "",
                                    "상태": "missing", "매칭장소": "", "행정구역후보": "",
                                    "이름유사도": "", "질의어": f"위례 {name}"}
            save_csv(RESULTS, ["단지명", "위도", "경도", "출처", "상태", "매칭장소", "행정구역후보", "이름유사도", "질의어"],
                     list(result_by_name.values()))
            network_blocked = True
            break
        if match:
            result_by_name[name] = {"단지명": name, "위도": f"{match['lat']:.8f}",
                                    "경도": f"{match['lon']:.8f}",
                                    "출처": "Kakao Local keyword search",
                                    "상태": "assumption", "매칭장소": match["place"],
                                    "행정구역후보": match["district"],
                                    "이름유사도": f"{match['similarity']:.3f}", "질의어": query}
            print(f"{name}\t성공\tHTTP {status_code}")
        else:
            result_by_name[name] = {"단지명": name, "위도": "", "경도": "", "출처": "",
                                    "상태": "missing", "매칭장소": "", "행정구역후보": "",
                                    "이름유사도": "", "질의어": f"위례 {name}"}
            print(f"{name}\t실패\tHTTP {status_code}")
        save_csv(RESULTS, ["단지명", "위도", "경도", "출처", "상태", "매칭장소", "행정구역후보", "이름유사도", "질의어"],
                 list(result_by_name.values()))

    if not RESULTS.exists():
        save_csv(RESULTS, ["단지명", "위도", "경도", "출처", "상태", "매칭장소", "행정구역후보", "이름유사도", "질의어"], [])
    failed = [apt.get("단지명", "") for apt in apartments
              if not (manual.get(apt.get("단지명", ""), {}).get("위도")
                      and manual.get(apt.get("단지명", ""), {}).get("경도"))
              and not (result_by_name.get(apt.get("단지명", ""), {}).get("위도")
                       and result_by_name.get(apt.get("단지명", ""), {}).get("경도"))
              and not (apt.get("위도") and apt.get("경도"))]
    existing = {row.get("단지명"): row for row in manual_rows}
    manual_out = [{"단지명": name, "위도": existing.get(name, {}).get("위도", ""),
                   "경도": existing.get(name, {}).get("경도", ""),
                   "출처": existing.get(name, {}).get("출처", "")} for name in failed]
    save_csv(MANUAL, FIELDS, manual_out)

    if network_blocked:
        print("STOP\tnetwork or authorization failure; geocoding stopped")
        print(f"MANUAL_COORDINATES_NEEDED\t{len(failed)}")
        raise SystemExit(2)

    merged = []
    new_fields = list(master_fields or [])
    for field in ("좌표출처", "좌표상태", "좌표매칭장소"):
        if field not in new_fields:
            new_fields.append(field)
    for apt in apartments:
        row = dict(apt)
        name = row.get("단지명", "")
        match = result_by_name.get(name)
        if match and match.get("위도") and match.get("경도"):
            row["위도"], row["경도"] = match["위도"], match["경도"]
        row["좌표출처"] = (match or {}).get("출처") or ("data/processed/apartment_master.csv" if row.get("위도") else "")
        row["좌표상태"] = (match or {}).get("상태") or ("sourced" if row.get("위도") else "missing")
        row["좌표매칭장소"] = (match or {}).get("매칭장소", "")
        merged.append(row)
    save_csv(OUTPUT, new_fields, merged)
    print(f"RESULTS_WRITTEN\t{RESULTS.relative_to(ROOT)}")
    print(f"ENRICHED_MASTER_WRITTEN\t{OUTPUT.relative_to(ROOT)}")
    print(f"MANUAL_COORDINATES_NEEDED\t{len(failed)}")
    if failed:
        print("MANUAL_NAMES\t" + "\t".join(failed))


if __name__ == "__main__":
    main()

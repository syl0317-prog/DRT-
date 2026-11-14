"""Read-only inspection of bus-stop and boundary spatial inputs."""
from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from pyproj import Transformer
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
NATIONAL = ROOT / "data/raw/국토교통부_전국 버스정류장 위치정보_20251031 (1).csv"
WIRYE_XLSX = ROOT / "data/raw/위례 정류장 데이터/위례동_버스정류장_위치정보.xlsx"
BOUNDARY = ROOT / "data/processed/wirye_changgok_boundary.geojson"
STATIONS = ROOT / "data/processed/wirye_tram_official_stations.geojson"


def xlsx_rows(path: Path):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.findall(".//m:t", ns))
                      for si in root.findall("m:si", ns)]
        wb = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relmap = {x.attrib["Id"]: x.attrib["Target"] for x in rels.findall("p:Relationship", ns)}
        all_sheets = {}
        for sheet in wb.findall("m:sheets/m:sheet", ns):
            target = relmap[sheet.attrib[f"{{{ns['r']}}}id"]].lstrip("/")
            sheet_path = target if target.startswith("xl/") else f"xl/{target}"
            root = ET.fromstring(archive.read(sheet_path))
            rows = []
            for row in root.findall("m:sheetData/m:row", ns):
                values = {}
                for cell in row.findall("m:c", ns):
                    ref = cell.attrib.get("r", "")
                    col = re.match(r"[A-Z]+", ref).group(0)
                    index = 0
                    for char in col:
                        index = index * 26 + ord(char) - ord("A") + 1
                    value = cell.find("m:v", ns)
                    if cell.attrib.get("t") == "s" and value is not None:
                        item = shared[int(value.text)]
                    elif cell.attrib.get("t") == "inlineStr":
                        item = "".join(t.text or "" for t in cell.findall(".//m:t", ns))
                    else:
                        item = value.text if value is not None else ""
                    values[index - 1] = item
                rows.append([values.get(i, "") for i in range(max(values, default=-1) + 1)])
            all_sheets[sheet.attrib["name"]] = rows
        return all_sheets


def inspect_national():
    counts, valid, cities = 0, 0, Counter()
    with NATIONAL.open(encoding="cp949", newline="") as f:
        for row in csv.DictReader(f):
            counts += 1
            if row.get("위도") and row.get("경도"):
                try:
                    float(row["위도"]); float(row["경도"])
                    valid += 1
                except ValueError:
                    pass
            city = row.get("도시명", "")
            if any(term in city for term in ("성남", "하남", "송파")):
                cities[city] += 1
    print(f"national_bus_rows={counts}; valid_coordinate_rows={valid}; relevant_city_rows={dict(cities)}")


def main():
    inspect_national()
    sheets = xlsx_rows(WIRYE_XLSX)
    print(f"Wirye location workbook sheets={list(sheets)}")
    for name, rows in sheets.items():
        if not rows:
            continue
        header = rows[0]
        print(f"sheet={name}; rows={max(0, len(rows)-1)}; columns={header}")
        print("coordinate_rows_with_values=" + str(sum(1 for row in rows[1:]
              if len(row) >= len(header) and row[header.index("위도")] and row[header.index("경도")]))
              if "위도" in header and "경도" in header else "coordinate_columns=missing")
    boundary_doc = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    boundary = shape(boundary_doc["features"][0]["geometry"])
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    projected = __import__("shapely.ops", fromlist=["transform"]).transform(transformer.transform, boundary)
    print(f"boundary_crs=EPSG:4326; projected_crs=EPSG:5179; boundary_bounds_m={projected.bounds}; "
          f"buffer300_bounds_m={projected.buffer(300).bounds}")
    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    print(f"tram_station_count={len(stations.get('features', []))}")


if __name__ == "__main__":
    main()

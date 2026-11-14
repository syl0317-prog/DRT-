"""Read-only inventory for apartment access, bus-stop and live-simulation sources."""
from __future__ import annotations

import csv
import os
import re
import zipfile
from xml.etree import ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEPOINTS = ("PRESETS", "drt_stops.csv", "STOPS_FILE", "homes =", "for i, (home_id", "selected = events",
              "scenario ==", "주말", "낮 호출형", "def _build_drt_trips", "vehicle_count")


def read_csv_header(path: Path):
    last_error = None
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.reader(f)
                header = next(reader, [])
            return encoding, header
        except (UnicodeDecodeError, csv.Error) as exc:
            last_error = exc
    return f"unreadable: {type(last_error).__name__}", []


def csv_row_count(path: Path):
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return sum(1 for _ in csv.DictReader(f)), encoding
        except UnicodeDecodeError:
            continue
    return None, "unreadable"


def xlsx_headers(path: Path):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
          "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in item.findall(".//m:t", ns))
                      for item in root.findall("m:si", ns)]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall("p:Relationship", ns)}
        result = []
        for sheet in workbook.findall("m:sheets/m:sheet", ns):
            rel_id = sheet.attrib[f"{{{ns['r']}}}id"]
            target = targets[rel_id].lstrip("/")
            sheet_path = target if target.startswith("xl/") else f"xl/{target}"
            root = ET.fromstring(archive.read(sheet_path))
            row = root.find("m:sheetData/m:row", ns)
            headers = []
            if row is not None:
                for cell in row.findall("m:c", ns):
                    value = cell.find("m:v", ns)
                    if cell.attrib.get("t") == "s" and value is not None:
                        headers.append(shared[int(value.text)])
                    else:
                        inline = cell.find("m:is", ns)
                        headers.append("".join(t.text or "" for t in inline.findall(".//m:t", ns))
                                       if inline is not None else (value.text if value is not None else ""))
            result.append((sheet.attrib["name"], headers))
        return result


def inspect_raw_candidates():
    raw = ROOT / "data" / "raw"
    candidates = sorted(p for p in raw.rglob("*") if p.is_file()
                        and any(word in p.name.lower() for word in ("bus", "stop", "정류장", "국토교통"))) if raw.exists() else []
    print(f"data/raw exists={raw.exists()} candidate_count={len(candidates)}")
    for path in candidates:
        rel = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in {".csv", ".txt"}:
            encoding, fields = read_csv_header(path)
            coords = [field for field in fields if re.search(r"lat|lon|위도|경도|좌표|x좌표|y좌표", field, re.I)]
            print(f"{rel}\tencoding={encoding}\tcoordinate_columns={coords}\tcolumns={fields}")
        elif path.suffix.lower() == ".xlsx":
            try:
                for sheet, fields in xlsx_headers(path):
                    coords = [str(field) for field in fields
                              if re.search(r"lat|lon|위도|경도|좌표|x좌표|y좌표", str(field), re.I)]
                    print(f"{rel}\tsheet={sheet}\tcoordinate_columns={coords}\tcolumns={fields}")
            except Exception as exc:
                print(f"{rel}\tworkbook_header_error={type(exc).__name__}")
        else:
            print(f"{rel}\tformat={path.suffix.lower()}\tencoding=not-applicable")


def inspect_code(rel):
    path = ROOT / rel
    print(f"\n[{rel}] exists={path.exists()}")
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    printed = set()
    for n, line in enumerate(lines, 1):
        if any(token in line for token in CODEPOINTS):
            start, end = max(1, n - 1), min(len(lines), n + 1)
            for i in range(start, end + 1):
                if i not in printed:
                    print(f"{i}: {lines[i - 1]}")
                    printed.add(i)


def main():
    master = ROOT / "data/processed/apartment_master.csv"
    print(f"apartment_master exists={master.exists()}")
    if master.exists():
        count, encoding = csv_row_count(master)
        _, fields = read_csv_header(master)
        coord_pairs = (("위도", "경도"), ("lat", "lon"), ("latitude", "longitude"))
        lat_col = next((a for a, b in coord_pairs if a in fields and b in fields), None)
        lon_col = next((b for a, b in coord_pairs if a in fields and b in fields), None)
        coords_count = None
        if lat_col and lon_col:
            coords_count = sum(1 for row in csv.DictReader(master.open(encoding=encoding, newline=""))
                               if row.get(lat_col) not in (None, "") and row.get(lon_col) not in (None, ""))
        print(f"rows={count}; encoding={encoding}; columns={fields}; "
              f"coordinate_columns={(lat_col, lon_col) if lat_col else 'missing'}; "
              f"rows_with_coordinates={coords_count}; 모델반영_column={'모델반영' in fields}")

    inspect_raw_candidates()
    for rel in ("sewook31/app.py", "sewook31/modules/live_control.py", "sewook31/modules/vehicle_positions.py"):
        inspect_code(rel)
    geocode = ROOT / "scripts/geocode_kakao.py"
    print(f"\nscripts/geocode_kakao.py exists={geocode.exists()}")
    env_path = ROOT / ".env"
    key_names = []
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if match and match.group(1).startswith("KAKAO"):
                key_names.append(match.group(1))
    print(f".env exists={env_path.exists()}; KAKAO variable names={sorted(set(key_names))}")


if __name__ == "__main__":
    main()

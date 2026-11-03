
import xml.etree.ElementTree as ET
from pathlib import Path

# 31번 버스 경유정류장 XML 파일
file_path = Path(__file__).parent / "성남331번_경유정류장.xml"

# 조사 대상 정류장 11개
target_stations = {
    "05174", "05290", "05291", "05292", "05293", "05294",
    "28370", "28469", "28470", "28471", "28473"
}

try:
    tree = ET.parse(file_path)
    root = tree.getroot()

    stations = root.findall(".//busRouteStationList")

    print("성남331번 버스 전체 경유정류장 수:", len(stations))
    print("\n===== 조사 대상 정류장과 비교 =====")

    matches = []

    for station in stations:
        number = (station.findtext("mobileNo") or "").strip()
        name = (station.findtext("stationName") or "").strip()

        if number.zfill(5) in target_stations:
            matches.append((number.zfill(5), name))
            print(f"일치: {number.zfill(5)} / {name}")

    if not matches:
        print("조사 대상 11개 정류장과 일치하는 곳이 없습니다.")

    print("\n일치 정류장 수:", len(matches))

except FileNotFoundError:
    print("XML 파일을 찾지 못했습니다. 파일 이름을 확인해 주세요.")

except ET.ParseError:
    print("XML 형식 오류입니다. XML 코드가 올바르게 저장되었는지 확인해 주세요.")

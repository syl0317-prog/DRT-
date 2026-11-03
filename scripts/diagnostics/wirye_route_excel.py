
from pathlib import Path
import xml.etree.ElementTree as ET
import pandas as pd

folder = Path(__file__).parent

# 조사 대상 정류장 13개
stations = [
    "28370", "28469", "28470", "28471", "28473",
    "05174", "05290", "05291", "05292", "05293", "05294",
    "28372", "28468"
]

# 노선별 저장한 XML 파일
routes = {
    "31": "하남31번_경유정류장.xml",
    "38": "하남38번_경유정류장.xml",
    "60": "성남60번_경유정류장.xml",
    "200": "성남200번_경유정류장.xml",
    "210": "성남210번_경유정류장.xml",
    "231": "성남231번_경유정류장.xml",
    "315": "성남315번_경유정류장.xml",
    "331": "성남331번_경유정류장.xml",
}

# 모든 정류장과 노선의 비교표
df = pd.DataFrame("X", index=stations, columns=list(routes) + ["위례-01"])

for route, filename in routes.items():
    path = folder / filename

    if not path.exists():
        print(f"파일 없음: {filename}")
        continue

    root = ET.parse(path).getroot()

    for item in root.findall(".//busRouteStationList"):
        number = item.findtext("mobileNo", "").strip().zfill(5)

        if number in df.index:
            df.loc[number, route] = "O"

# 추가 확인한 두 정류장
for number in ["28372", "28468"]:
    for route in ["31", "38", "200", "210", "231", "315", "331"]:
        df.loc[number, route] = "O"

# 위례-01번: 네이버 지도에서 확인한 정류장
wirye01 = [
    "28370", "28470", "28471", "28473",
    "28469", "28468", "28372"
]

for number in wirye01:
    df.loc[number, "위례-01"] = "O"

df.index.name = "정류장번호"
df["경유노선수"] = (df == "O").sum(axis=1)

output = folder / "위례동_13개정류장_버스노선_비교.xlsx"
df.to_excel(output)

print("엑셀 파일 생성 완료!")
print("저장 위치:", output)
print(df)

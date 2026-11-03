import requests
import xml.etree.ElementTree as ET
from getpass import getpass

SERVICE_KEY = getpass("API 인증키 입력: ").strip()

url = "https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getCrdntPrxmtSttnList"

params = {
    "serviceKey": SERVICE_KEY,
    "gpsLati": 37.4724476974197,
    "gpsLong": 127.153792052296,
    "numOfRows": 100,
    "pageNo": 1,
    "_type": "xml"
}

response = requests.get(url, params=params, timeout=30)

print("HTTP 상태:", response.status_code)

root = ET.fromstring(response.content)

print("결과코드:", root.findtext(".//resultCode"))
print("결과메시지:", root.findtext(".//resultMsg"))

items = root.findall(".//item")

print("조회된 정류소 수:", len(items))

for item in items:
    print({
        child.tag: child.text
        for child in item
    })

import pandas as pd

# API에서 조회된 정류소 정보를 표로 변환
data = []

for item in items:
    data.append({
        "정류소ID": item.findtext("nodeid"),
        "정류소번호": item.findtext("nodeno"),
        "정류소명": item.findtext("nodenm"),
        "위도": item.findtext("gpslati"),
        "경도": item.findtext("gpslong")
    })

df = pd.DataFrame(data)
from math import radians, sin, cos, sqrt, atan2

# 위례 호반써밋 에비뉴 대표 좌표
apt_lat = 37.4724476974197
apt_lon = 127.153792052296

# 두 좌표 사이의 직선거리 계산 (미터)
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return round(R * c, 1)

# 정류소별 거리 계산
df["직선거리(m)"] = df.apply(
    lambda row: calculate_distance(
        apt_lat,
        apt_lon,
        float(row["위도"]),
        float(row["경도"])
    ),
    axis=1
)

# 가까운 정류소 순서로 정렬
df = df.sort_values("직선거리(m)")

# 500m 이내 정류소만 추출
df = df[df["직선거리(m)"] <= 500]
# 아파트 이름 추가
df["아파트명"] = "위례 호반써밋 에비뉴"

# 거리별 접근성 분류
def accessibility(distance):
    if distance <= 200:
        return "접근성 양호"
    elif distance <= 300:
        return "접근성 보통"
    else:
        return "접근성 상대적 취약"

df["접근성 평가"] = df["직선거리(m)"].apply(accessibility)

# 엑셀 열 순서 정리
df = df[
    [
        "아파트명",
        "정류소ID",
        "정류소번호",
        "정류소명",
        "위도",
        "경도",
        "직선거리(m)",
        "접근성 평가"
    ]
]

print(df[["정류소명", "직선거리(m)", "접근성 평가"]])

print("500m 이내 정류소 수:", len(df))

# 엑셀 파일 저장
filename = "위례_호반써밋_버스정류소.xlsx"

df.to_excel(filename, index=False)

print(f"엑셀 저장 완료: {filename}")

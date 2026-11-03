
import requests
import pandas as pd
import xml.etree.ElementTree as ET
from getpass import getpass
from pathlib import Path
import time

# =====================================
# 1. TAGO API 설정
# =====================================

URL = (
    "https://apis.data.go.kr/1613000/"
    "BusSttnInfoInqireService/getSttnNoList"
)

API_KEY = getpass("TAGO 일반 인증키 입력: ").strip()

# =====================================
# 2. 조사 대상 정류장
# =====================================

stations = [
    ("31020", "05174", "위례더힐남문"),
    ("31020", "05290", "위례더힐정문"),
    ("31020", "05291", "위례그린파크푸르지오"),
    ("31020", "05292", "위례호반써밋에비뉴"),
    ("31020", "05293", "위례센트럴푸르지오"),
    ("31020", "05294", "위례센트럴푸르지오"),

    ("31180", "28370", "하남시위례동행정복지센터"),
    ("31180", "28469", "위례롯데캐슬"),
    ("31180", "28470", "위례그린파크푸르지오"),
    ("31180", "28471", "위례롯데캐슬"),
    ("31180", "28473", "위례롯데캐슬"),
]

# =====================================
# 3. 정류장 조회 함수
# =====================================

def search_station(city_code, station_no, station_name):

    params = {
        "serviceKey": API_KEY,
        "pageNo": 1,
        "numOfRows": 100,
        "_type": "xml",
        "cityCode": city_code,
        "nodeNm": station_name
    }

    response = requests.get(
        URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    root = ET.fromstring(response.content)

    result_code = root.findtext(".//resultCode")

    if result_code != "00":
        raise ValueError(
            "API 결과 코드: " + str(result_code)
        )

    # 검색 결과 중 정류장번호가 일치하는 항목 선택
    for item in root.findall(".//item"):

        node_no = item.findtext("nodeno", "").strip()

        if node_no.zfill(5) == station_no:

            return {
                "지역": "성남시" if city_code == "31020" else "하남시",
                "도시코드": city_code,
                "정류장번호": station_no,
                "정류장ID": item.findtext("nodeid", ""),
                "정류장명": item.findtext("nodenm", ""),
                "위도": item.findtext("gpslati", ""),
                "경도": item.findtext("gpslong", ""),
                "조회상태": "성공"
            }

    return {
        "지역": "성남시" if city_code == "31020" else "하남시",
        "도시코드": city_code,
        "정류장번호": station_no,
        "정류장ID": "",
        "정류장명": station_name,
        "위도": "",
        "경도": "",
        "조회상태": "일치 항목 없음"
    }


# =====================================
# 4. 11개 정류장 자동 조회
# =====================================

results = []

for city_code, station_no, station_name in stations:

    print(f"조회 중: {station_no} / {station_name}")

    try:
        result = search_station(
            city_code,
            station_no,
            station_name
        )

        results.append(result)

        print("결과:", result["조회상태"])

    except Exception as e:

        results.append({
            "지역": "성남시" if city_code == "31020" else "하남시",
            "도시코드": city_code,
            "정류장번호": station_no,
            "정류장ID": "",
            "정류장명": station_name,
            "위도": "",
            "경도": "",
            "조회상태": "오류: " + type(e).__name__
        })

        print("오류:", type(e).__name__)

    time.sleep(0.3)


# =====================================
# 5. 엑셀 파일 저장
# =====================================

df = pd.DataFrame(results)

output_file = (
    Path(__file__).resolve().parent
    / "위례동_버스정류장_위치정보.xlsx"
)

df.to_excel(
    output_file,
    index=False
)

# =====================================
# 6. 결과 확인
# =====================================

success = (df["조회상태"] == "성공").sum()

print("\n==============================")
print("위례동 버스정류장 데이터 수집 완료")
print("==============================")

print("전체 정류장:", len(df))
print("조회 성공:", success)
print("조회 실패:", len(df) - success)

print("\n저장 파일:", output_file.name)

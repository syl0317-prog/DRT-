
import math
import time
import getpass

import requests
import pandas as pd

# 1. API 주소
URL = (
    "https://apis.data.go.kr/1613000/"
    "BusRoutespecificStopInformation/"
    "getBusRoutespecificStopInformation"
)

# 2. 인증키 입력
API_KEY = getpass.getpass(
    "공공데이터포털 인증키를 입력하세요: "
).strip()

# 3. 조회 조건
PARAMS = {
    "serviceKey": API_KEY,
    "pageNo": 1,
    "numOfRows": 100,
    "opr_ymd": "20260916",
    "ctpv_cd": "41",
    "sgg_cd": "41131",
    "dataType": "JSON"
}

def get_page(page_no):
    PARAMS["pageNo"] = page_no

    response = requests.get(
        URL,
        params=PARAMS,
        timeout=30
    )
    response.raise_for_status()

    try:
        result = response.json()
    except ValueError:
        print("서버 응답:", response.text[:500])
        raise RuntimeError("JSON 형식으로 응답하지 않았습니다.")

    data = result.get("Response", result)
    header = data.get("header", {})

    if str(header.get("resultCode")) != "200":
        raise RuntimeError(
            f"API 오류: {header}"
        )

    body = data.get("body", {})
    total_count = int(body.get("totalCount", 0))

    items = body.get("items", {})
    if isinstance(items, dict):
        rows = items.get("item", [])
    elif isinstance(items, list):
        rows = items
    else:
        rows = []

    if isinstance(rows, dict):
        rows = [rows]

    return rows, total_count


# 4. 첫 번째 페이지 조회
print("첫 번째 페이지 조회 중...")

all_data, total_count = get_page(1)

if not all_data:
    raise RuntimeError(
        "조회 결과가 없습니다. 날짜와 지역 코드를 확인하세요."
    )

total_pages = math.ceil(total_count / 100)

print("전체 데이터 수:", total_count)
print("전체 페이지 수:", total_pages)

# 5. 전체 페이지 수집
for page in range(2, total_pages + 1):
    rows, _ = get_page(page)
    all_data.extend(rows)

    print(f"{page}/{total_pages}페이지 수집 완료")
    time.sleep(0.3)

# 6. 데이터프레임 생성
df = pd.DataFrame(all_data)
df = df.drop_duplicates()

# 정류장 순서 숫자로 변환
if "sttn_seq" in df.columns:
    df["sttn_seq"] = pd.to_numeric(
        df["sttn_seq"],
        errors="coerce"
    )

# 노선ID와 정류장 순서로 정렬
df = df.sort_values(
    ["rte_id", "sttn_seq"]
)

# 7. 창곡동 정류장 추출
wirye_stops = df[
    df["emd_nm"].astype(str).str.strip() == "창곡동"
].copy()

# 8. 창곡동 경유 버스 노선 추출
wirye_routes = (
    wirye_stops[["rte_id", "rte_no", "rte_nm"]]
    .drop_duplicates()
    .sort_values("rte_no")
)

# 9. 해당 노선의 수정구 내 정류장 추출
route_stops = df[
    df["rte_id"].isin(wirye_routes["rte_id"])
].copy()

# 10. 엑셀 저장
file_name = "성남시_위례동_버스노선_분석.xlsx"

with pd.ExcelWriter(
    file_name,
    engine="openpyxl"
) as writer:

    df.to_excel(
        writer,
        sheet_name="수정구_전체",
        index=False
    )

    wirye_stops.to_excel(
        writer,
        sheet_name="창곡동_정류장",
        index=False
    )

    wirye_routes.to_excel(
        writer,
        sheet_name="위례동_경유노선",
        index=False
    )

    route_stops.to_excel(
        writer,
        sheet_name="경유노선_수정구정류장",
        index=False
    )

print("\n엑셀 저장 완료!")
print("파일명:", file_name)
print("전체 수집 행:", len(df))
print("창곡동 경유 노선:", len(wirye_routes))

import requests
from getpass import getpass

# 카카오 API 키 입력
api_key = getpass("카카오 REST API 키 입력: ").strip()

# 아파트 주소
address = "경기 성남시 수정구 위례중앙로 216"

url = "https://dapi.kakao.com/v2/local/search/address.json"

headers = {
    "Authorization": "KakaoAK " + api_key
}

params = {
    "query": address
}

response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=30
)

print("HTTP 상태:", response.status_code)
print("카카오 응답:", response.text)

response.raise_for_status()

data = response.json()

if data["documents"]:
    result = data["documents"][0]

    latitude = float(result["y"])
    longitude = float(result["x"])

    print("아파트명: 위례 호반써밋 에비뉴")
    print("주소:", address)
    print("위도:", latitude)
    print("경도:", longitude)
else:
    print("검색 결과가 없습니다.")

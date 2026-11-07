import os
import datetime
import xml.etree.ElementTree as ET
import pandas as pd
import requests
from dotenv import load_dotenv

# .env 로드 (키 값 자체는 출력하거나 저장하지 않음)
load_dotenv('.env')
api_key = os.getenv('PUBLIC_DATA_SERVICE_KEY') or os.getenv('DATA_GO_KR_API_KEY') or ''

target_routes = [
    {"label": "31", "route_no": "31", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남60", "route_no": "60", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남200", "route_no": "200", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남210", "route_no": "210", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남231", "route_no": "231", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남315", "route_no": "315", "city_hint": "성남", "city_code": "31020"},
    {"label": "성남331", "route_no": "331", "city_hint": "성남", "city_code": "31020"},
    {"label": "하남31", "route_no": "31", "city_hint": "하남", "city_code": "31180"},
    {"label": "하남38", "route_no": "38", "city_hint": "하남", "city_code": "31180"}
]

query_date = datetime.date.today().strftime('%Y-%m-%d')

api_status_report = {}

def check_api_key_validity():
    status = {}
    
    # 1. 국토부 TAGO API 테스트
    tago_test_url = "https://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteNoList"
    try:
        r = requests.get(tago_test_url, params={'serviceKey': api_key, 'cityCode': '31020', 'routeNo': '60', 'numOfRows': 1}, timeout=10)
        if r.status_code == 200 and '<resultCode>00</resultCode>' in r.text:
            status['TAGO'] = {'ok': True, 'msg': '정상 호출 가능'}
        else:
            status['TAGO'] = {'ok': False, 'http_code': r.status_code, 'msg': f"호출 실패 (HTTP {r.status_code})"}
            if '<returnAuthMsg>' in r.text:
                root = ET.fromstring(r.text)
                auth_msg = root.findtext('.//returnAuthMsg') or root.findtext('.//errMsg')
                status['TAGO']['msg'] = f"호출 거부 (HTTP {r.status_code}: {auth_msg})"
            elif '<resultMsg>' in r.text:
                root = ET.fromstring(r.text)
                result_msg = root.findtext('.//resultMsg')
                status['TAGO']['msg'] = f"오류 ({result_msg})"
    except Exception as e:
        status['TAGO'] = {'ok': False, 'msg': f"연결 오류 ({type(e).__name__})"}

    # 2. 경기도 GBIS API 테스트
    gbis_test_url = "http://apis.data.go.kr/6410000/busrouteservice/getBusRouteList"
    try:
        r = requests.get(gbis_test_url, params={'serviceKey': api_key, 'keyword': '60'}, timeout=10)
        if r.status_code == 200 and '<resultCode>0</resultCode>' in r.text:
            status['GBIS'] = {'ok': True, 'msg': '정상 호출 가능'}
        else:
            status['GBIS'] = {'ok': False, 'http_code': r.status_code, 'msg': f"호출 실패 (HTTP {r.status_code})"}
            if '<returnAuthMsg>' in r.text:
                root = ET.fromstring(r.text)
                auth_msg = root.findtext('.//returnAuthMsg') or root.findtext('.//errMsg')
                status['GBIS']['msg'] = f"호출 거부 (HTTP {r.status_code}: {auth_msg})"
            elif '<resultMessage>' in r.text:
                root = ET.fromstring(r.text)
                result_msg = root.findtext('.//resultMessage')
                status['GBIS']['msg'] = f"오류 ({result_msg})"
    except Exception as e:
        status['GBIS'] = {'ok': False, 'msg': f"연결 오류 ({type(e).__name__})"}

    return status

results = []
api_status = check_api_key_validity()
print("API 상태 점검 결과:")
for api_name, info in api_status.items():
    print(f" - {api_name}: {info['msg']}")

for route in target_routes:
    label = route["label"]
    row = {
        "노선번호": label,
        "운수회사": "미확인",
        "첨두배차_분": "미확인",
        "비첨두배차_분": "미확인",
        "첫차": "미확인",
        "막차": "미확인",
        "출처(API명)": "미확인",
        "조회일": query_date
    }
    
    # GBIS 우선 시도
    if api_status['GBIS']['ok']:
        try:
            # getBusRouteList
            r = requests.get("http://apis.data.go.kr/6410000/busrouteservice/getBusRouteList",
                             params={'serviceKey': api_key, 'keyword': route['route_no']}, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                items = root.findall('.//busRouteList')
                matched_id = None
                for it in items:
                    rname = it.findtext('routeName', '')
                    reg = it.findtext('regionName', '')
                    if rname == route['route_no'] and route['city_hint'] in reg:
                        matched_id = it.findtext('routeId')
                        break
                if matched_id:
                    # getBusRouteInfoItem
                    r_info = requests.get("http://apis.data.go.kr/6410000/busrouteservice/getBusRouteInfoItem",
                                          params={'serviceKey': api_key, 'routeId': matched_id}, timeout=10)
                    if r_info.status_code == 200:
                        info_root = ET.fromstring(r_info.content)
                        item = info_root.find('.//busRouteInfoItem')
                        if item is not None:
                            row["운수회사"] = item.findtext('companyName', '') or "미확인"
                            row["첨두배차_분"] = item.findtext('peekAlloc', '') or "미확인"
                            row["비첨두배차_분"] = item.findtext('nPeekAlloc', '') or "미확인"
                            row["첫차"] = item.findtext('upFirstTime', '') or "미확인"
                            row["막차"] = item.findtext('upLastTime', '') or "미확인"
                            row["출처(API명)"] = "경기도 GBIS (노선정보항목조회)"
        except Exception:
            pass

    # TAGO 시도 (GBIS에서 못 가져온 경우)
    if row["출처(API명)"] == "미확인" and api_status['TAGO']['ok']:
        try:
            r = requests.get("https://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteNoList",
                             params={'serviceKey': api_key, 'cityCode': route['city_code'], 'routeNo': route['route_no']}, timeout=10)
            if r.status_code == 200:
                root = ET.fromstring(r.content)
                items = root.findall('.//item')
                matched_id = None
                for it in items:
                    rno = it.findtext('routeno', '')
                    if str(rno) == str(route['route_no']):
                        matched_id = it.findtext('routeid')
                        break
                if matched_id:
                    r_info = requests.get("https://apis.data.go.kr/1613000/BusRouteInfoInqireService/getRouteInfoIem",
                                          params={'serviceKey': api_key, 'cityCode': route['city_code'], 'routeId': matched_id}, timeout=10)
                    if r_info.status_code == 200:
                        info_root = ET.fromstring(r_info.content)
                        item = info_root.find('.//item')
                        if item is not None:
                            alloc = item.findtext('intervaltime', '') or "미확인"
                            row["첨두배차_분"] = alloc
                            row["비첨두배차_분"] = alloc
                            row["첫차"] = item.findtext('startvehicletime', '') or "미확인"
                            row["막차"] = item.findtext('endvehicletime', '') or "미확인"
                            row["출처(API명)"] = "국토교통부 TAGO (버스노선정보)"
        except Exception:
            pass

    # API 모두 호출 실패한 경우 출처 명시
    if row["출처(API명)"] == "미확인":
        # API 권한 거부/누락 상태 기록
        reasons = []
        for api_name, info in api_status.items():
            if not info['ok']:
                reasons.append(f"{api_name}: {info['msg']}")
        row["출처(API명)"] = "호출 거부 (" + "; ".join(reasons) + ")"

    results.append(row)

df = pd.DataFrame(results)
os.makedirs('data/assumptions', exist_ok=True)
out_csv = 'data/assumptions/bus_routes_real.csv'
df.to_csv(out_csv, index=False, encoding='utf-8-sig')
print(f"저장 완료: {out_csv}")
print(df.to_string())

"""105/106번 전용 읽기 전용 API 진단. 원본 데이터는 변경하지 않는다.

python -B diagnose_tram_105_106.py --self-test
python -B diagnose_tram_105_106.py
인증정보/요청 URL/원본 응답/예외 문자열은 출력 또는 저장하지 않는다.
"""
import ast
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data/raw/위례 정류장 데이터"
OUT_DIR = ROOT / "data/processed"
load_dotenv(ROOT / ".env")

API = 'https://apis.data.go.kr/1613000/BusSttnInfoInqireService/getCrdntPrxmtSttnList'
BANDS = ['300m 이내', '300m 초과~500m 이내', '500m 초과', '좌표 오류']
ERRORS = {
    '22': 'API 호출 횟수 제한 초과', '30': '등록되지 않은 인증키',
    '31': '인증키 사용기간 만료', '32': '등록되지 않은 IP',
    '10': '잘못된 요청 파라미터', '12': '서비스 접근 거부',
    '20': '서비스 접근 거부', '01': 'API 애플리케이션 오류',
}


def distance(a, b, c, d):
    x = math.sin(math.radians(c-a)/2)**2
    x += math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(math.radians(d-b)/2)**2
    return 2*6371000*math.asin(math.sqrt(max(0, min(1, x))))


def band(m):
    return BANDS[0] if m <= 300 else BANDS[1] if m <= 500 else BANDS[2]


def valid(a, b):
    return math.isfinite(a) and math.isfinite(b) and -90 <= a <= 90 and -180 <= b <= 180


def credential():
    # 환경변수 우선 확인
    for key_name in ('PUBLIC_DATA_SERVICE_KEY', 'DATA_GO_KR_API_KEY'):
        if os.environ.get(key_name):
            return os.environ[key_name].strip()

    # 기존 코드가 참조하는 환경변수 이름 추출 (있을 경우)
    collector_path = ROOT / 'scripts/wirye_bus_stations.py'
    names = []
    if collector_path.exists():
        try:
            tree = ast.parse(collector_path.read_text(encoding='utf-8-sig'))
            for n in ast.walk(tree):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'getenv':
                    if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                        names.append(n.args[0].value)
                    elif n.args and isinstance(n.args[0], ast.Str):
                        names.append(n.args[0].s)
        except Exception:
            pass

    for name in names:
        if os.environ.get(name):
            return os.environ[name].strip()

    # 단일 행 KEY=value 및 따옴표 값을 처리하며 내용을 출력하지 않는다.
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].lstrip()
            name, sep, value = line.partition('=')
            if sep and (name.strip() in names or name.strip() in ('PUBLIC_DATA_SERVICE_KEY', 'DATA_GO_KR_API_KEY')):
                value = value.strip()
                if value[:1] in ('\"', "'"):
                    quote = value[0]
                    end = value.find(quote, 1)
                    value = value[1:end] if end >= 1 else ''
                else:
                    value = value.split(' #', 1)[0].strip()
                if value and '${' not in value:
                    return value
    return None


def parse_payload(raw):
    try:
        data = json.loads(raw.decode('utf-8-sig'))
        response = data['response']
        header = response['header']
        code = str(header.get('resultCode', 'MISSING'))
        if code not in ('00', '0'):
            return None, 'API 오류: '+ERRORS.get(code, '미분류 API 오류'), code
        body = response['body']
        items = body.get('items') or {}
        rows = items.get('item', []) if isinstance(items, dict) else []
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows):
            raise ValueError()
        total = int(body['totalCount'])
        if total < 0:
            raise ValueError()
        return (rows, total), '', '00'
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        try:
            root = ET.fromstring(raw)
            code = root.findtext('.//returnReasonCode') or root.findtext('.//resultCode')
            if code and code.isdigit() and len(code) <= 3:
                return None, 'API XML 오류: '+ERRORS.get(code, '미분류 API 오류'), code
        except ET.ParseError:
            pass
        return None, '응답 형식 오류(JSON 파싱 또는 필수 필드 누락)', ''


def fetch(lat, lon, key, number, pages):
    all_rows, seen, declared = [], set(), None
    for page in range(1, 101):
        params = dict(serviceKey=urllib.parse.unquote(key), gpsLati=lat, gpsLong=lon,
                      numOfRows=100, pageNo=page, _type='json')
        status, code, reason, payload = '', '', '', None
        try:
            # 프록시/요청 디버그 로그를 사용하지 않는다.
            request = urllib.request.Request(API+'?'+urllib.parse.urlencode(params))
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                payload, reason, code = parse_payload(response.read())
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload, reason, code = parse_payload(exc.read())
            reason = 'HTTP 오류 '+str(status)+('; '+reason if reason else '')
            payload = None
        except (socket.timeout, TimeoutError):
            reason = '네트워크 시간 초과'
        except urllib.error.URLError as exc:
            reason = '네트워크 연결 실패(DNS/TLS/프록시/접근 제한 등)'
            if isinstance(exc.reason, socket.gaierror):
                reason = 'DNS 이름 해석 실패'
            if isinstance(exc.reason, socket.timeout):
                reason = '네트워크 시간 초과'
            error_number = getattr(exc.reason, 'errno', None)
            if isinstance(error_number, int):
                reason += ' (OS 오류번호: {})'.format(error_number)
        except Exception:
            reason = '요청 처리 실패(민감정보 보호를 위해 원본 예외 미기록)'
        rows, total = payload if payload is not None else ([], '')
        pages.append(dict(트램정거장번호=number, 페이지=page, HTTP상태=status,
                          API결과코드=code, API전체건수=total, 페이지반환건수=len(rows), 실패원인=reason))
        if reason:
            return all_rows, declared, reason
        if declared is not None and total != declared:
            return all_rows, declared, '페이지 간 totalCount 변경: 수집 불완전'
        declared = total
        if not rows:
            return all_rows, declared, '' if len(all_rows) == total else '전체건수 이전 빈 페이지: 수집 불완전'
        fingerprint = json.dumps(rows, sort_keys=True, ensure_ascii=True)
        if fingerprint in seen:
            return all_rows, declared, '동일 페이지 반복: 수집 불완전'
        seen.add(fingerprint)
        all_rows.extend(rows)
        if len(all_rows) >= total:
            return all_rows, declared, '' if len(all_rows) == total else '전체건수와 누적 반환건수 불일치'
    return all_rows, declared, '페이지 상한(100) 도달: 수집 불완전'


def write_csv(path, fields, rows):
    with path.open('x', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def original_hashes():
    if not DATA_DIR.exists():
        return {}
    return {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in DATA_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in ('.csv', '.xlsx', '.xls', '.py')
            and f.name != Path(__file__).name}


def main():
    before = original_hashes()
    now = datetime.now(timezone(timedelta(hours=9)))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / ('diagnostics_105_106_'+now.strftime('%Y%m%d_%H%M%S_%f'))
    out.mkdir(parents=True, exist_ok=True)

    tram_csv = DATA_DIR / '위례_트램정거장_좌표.csv'
    if not tram_csv.exists():
        print(f"좌표 파일 부재: {tram_csv}")
        return

    with tram_csv.open(encoding='utf-8-sig') as handle:
        source = list(csv.DictReader(io.StringIO(''.join(line for line in handle if line.strip()))))
    key = credential()
    details, summaries, pages = [], [], []
    for number in (105, 106):
        matches = [r for r in source if str(r.get('정거장번호', '')).strip() == str(number)]
        s = dict(트램정거장번호=number, 트램정거장명='', 트램위도='', 트램경도='', 좌표검사='',
                 API상태='', API전체건수='', 실제반환건수='', 고유정류장수='',
                 **{x: '' for x in BANDS}, 최근접거리_m='', 진단='', 실패원인='')
        if len(matches) != 1:
            s.update(좌표검사='오류', API상태='미호출', 진단='원본 좌표 행 누락 또는 중복')
            summaries.append(s)
            continue
        row = matches[0]
        s['트램정거장명'] = row['정거장명']
        try:
            lat, lon = float(row['위도']), float(row['경도'])
            if not valid(lat, lon) or not (37.4 <= lat <= 37.6 and 127 <= lon <= 127.3):
                raise ValueError()
            s.update(트램위도=lat, 트램경도=lon, 좌표검사='수치·위례 범위 정상; 공식 위치 일치 여부 미검증')
        except (ValueError, TypeError):
            s.update(좌표검사='오류', API상태='미호출', 진단='좌표 오류')
            summaries.append(s)
            continue
        if not key:
            s.update(API상태='미호출', 진단='판정 불가', 실패원인='인증정보를 찾지 못함 또는 지원하지 않는 인증정보 형식')
            summaries.append(s)
            continue
        rows, total, reason = fetch(lat, lon, key, number, pages)
        counts = {x: 0 for x in BANDS}
        unique, distances = set(), []
        for index, bus in enumerate(rows, 1):
            item = dict(트램정거장번호=number, 트램정거장명=row['정거장명'], 트램위도=lat, 트램경도=lon,
                        반환순서=index, 버스정류장ID=bus.get('nodeid', ''), 버스정류장번호=bus.get('nodeno', ''),
                        버스정류장명=bus.get('nodenm', ''), 버스위도='', 버스경도='', 직선거리_m='', 거리구간='좌표 오류')
            try:
                a, b = float(bus['gpslati']), float(bus['gpslong'])
                if not valid(a, b) or (a == 0 and b == 0):
                    raise ValueError()
                m = distance(lat, lon, a, b)
                item.update(버스위도=a, 버스경도=b, 직선거리_m=round(m, 6), 거리구간=band(m))
                distances.append(m)
            except (ValueError, KeyError, TypeError):
                pass
            ident = str(bus.get('nodeid') or (bus.get('nodenm'), bus.get('gpslati'), bus.get('gpslong')))
            item['중복반환'] = '예' if ident in unique else '아니오'
            unique.add(ident)
            counts[item['거리구간']] += 1
            details.append(item)
        if reason:
            result = 'API 실패/수집 불완전: 0건으로 해석 금지'
        elif not rows:
            result = 'API 정상 응답 0건; 실제 정류장 부재/좌표 정확성을 의미하지 않음'
        elif counts[BANDS[0]]:
            result = '300m 이내 정류장 존재: 기존 결과와 차이(과거 실행 원인 미확정)'
        elif counts[BANDS[3]]:
            result = '유효 좌표 정류장은 모두 300m 초과; 좌표 오류 항목 때문에 전체 판정 제한'
        else:
            result = '정류장은 반환되지만 모두 300m 초과'
        s.update(API상태='실패/불완전' if reason else '성공', API전체건수=total if total is not None else '',
                 실제반환건수=len(rows), 고유정류장수=len(unique), 최근접거리_m=round(min(distances), 6) if distances else '',
                 진단=result, 실패원인=reason, **counts)
        summaries.append(s)
    detail_fields = ['트램정거장번호','트램정거장명','트램위도','트램경도','반환순서','버스정류장ID','버스정류장번호','버스정류장명','버스위도','버스경도','직선거리_m','거리구간','중복반환']
    write_csv(out/'정류장별_거리진단.csv', detail_fields, details)
    write_csv(out/'정거장별_진단요약.csv', list(summaries[0]), summaries)
    write_csv(out/'API_페이지별_호출상태.csv', ['트램정거장번호','페이지','HTTP상태','API결과코드','API전체건수','페이지반환건수','실패원인'], pages)
    unchanged = before == original_hashes()
    lines = ['105·106번 버스정류장 API 진단', '실행 시각: '+now.isoformat(),
             'API: '+API, '분석 기준: d ≤ 300m / 300m < d ≤ 500m / d > 500m. 반올림 전 거리로 분류.',
             '집계는 반환 행 기준이며 중복 여부와 고유 정류장 수를 별도 제공한다.',
             '실패/불완전 상태의 건수는 수집된 부분 결과만 뜻한다. 특히 반환 0건은 API 정상 응답 0건이 아니다.',
             'API는 반경 500m 주변 검색 서비스이므로 500m 초과 0건은 그 밖의 정류장 부재를 의미하지 않는다.',
             '공식 설명: https://www.data.go.kr/data/15096280/standard.do?recommendDataYn=Y',
             '좌표는 원본의 지도추정 값. 수치·범위 검사는 공식 정거장 위치 검증을 대체하지 않는다.', '']
    for s in summaries:
        lines.extend(['{}번 {}'.format(s['트램정거장번호'], s['트램정거장명'])]+['- {}: {}'.format(k,v) for k,v in s.items() if k not in ('트램정거장번호','트램정거장명')]+[''])
    lines.extend(['기존 수집 코드 점검:',
                  '- 위경도 요청 순서와 Haversine(지구 반지름 6,371,000m), 300m 포함 필터는 정상.',
                  '- 기존 페이지네이션은 totalCount까지 수집하지만 반복 페이지/전체건수 불일치 감지가 없다.',
                  '- 기존 코드는 조회 실패·정상 0건·전부 300m 초과를 저장 결과에서 구분하지 못한다.',
                  '- 기존 오류 문자열 출력은 요청 URL과 인증정보를 포함할 수 있어 본 진단은 고정 오류 설명만 기록한다.',
                  '- 본 진단은 HTTP/API 오류, XML 오류 응답, 페이지 반복·조기 종료, 좌표 오류를 별도 기록한다.',
                  '- 과거 실행의 API 응답이 없어 이번 결과만으로 과거 누락 원인을 확정할 수 없다.',
                  '원본 Python/CSV/Excel SHA-256 전후 동일: '+str(unchanged)])
    (out/'진단결과_한국어요약.txt').write_text('\n'.join(lines), encoding='utf-8-sig')
    print('진단 결과 저장: '+str(out))
    for s in summaries:
        print('{}번: {} / 반환 {}건 / 300m 이내 {} / 실패원인 {}'.format(s['트램정거장번호'],s['진단'],s['실제반환건수'],s[BANDS[0]],s['실패원인']))
    print('원본 파일 보존 확인: '+str(unchanged))


def self_test():
    assert distance(37.48,127.14,37.48,127.14) == 0
    assert abs(distance(0,0,0,1)-111194.92664455874) < 0.001
    assert [band(x) for x in (300,300.0001,500,500.0001)] == [BANDS[0],BANDS[1],BANDS[1],BANDS[2]]
    assert not valid(float('nan'),127)
    for items, expected in [('',0), ({'item':{'nodeid':'x'}},1)]:
        raw=json.dumps({'response':{'header':{'resultCode':'00'},'body':{'items':items,'totalCount':expected}}}).encode()
        assert len(parse_payload(raw)[0][0]) == expected
    assert parse_payload(b'<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>')[2] == '30'
    print('거리 경계/좌표/응답 파싱 자체 검증 통과(API 미호출)')


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        self_test()
    else:
        try:
            main()
        except Exception:
            print('진단 실행 실패: 입력/출력/설정 처리 오류. 인증정보 보호를 위해 원본 예외는 출력하지 않습니다.')
            sys.exit(1)

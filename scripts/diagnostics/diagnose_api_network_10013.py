"""네트워크 읽기 전용 점검. 보안 설정 변경/인증정보 로그를 하지 않는다."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import runpy
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = Path(__file__).resolve().parent
HOST = 'apis.data.go.kr'
RESULT = ROOT / ('network_diagnostics_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))


def error_info(exc):
    # 예외 문자열과 요청 URL은 저장하지 않는다.
    reasons = [exc]
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, BaseException):
        reasons.append(exc.reason)
    return [{'유형': type(e).__name__, 'errno': getattr(e, 'errno', None),
             'winerror': getattr(e, 'winerror', None)} for e in reasons]


def probe(name, operation):
    try:
        return {'검사': name, '성공': True, '결과': operation()}
    except Exception as exc:
        return {'검사': name, '성공': False, '오류': error_info(exc)}


def tcp(host, port):
    with socket.create_connection((host, port), timeout=8):
        return 'TCP 연결 성공'


def tls():
    with socket.create_connection((HOST, 443), timeout=8) as sock:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=HOST) as conn:
            return {'TLS': conn.version(), '인증서검증': '성공'}


def https(use_proxy):
    handler = urllib.request.ProxyHandler() if use_proxy else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)
    try:
        with opener.open('https://' + HOST + '/', timeout=10) as response:
            return {'HTTP': response.status}
    except urllib.error.HTTPError as exc:
        return {'HTTP': exc.code, '설명': 'HTTP 오류도 HTTPS 서버 응답 도달 증거'}


def hashes():
    return {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in ROOT.iterdir()
            if f.is_file() and f.suffix in ('.csv', '.xlsx', '.xls', '.py')}


def main():
    before = hashes()
    RESULT.mkdir()
    results = []
    addresses = []
    def dns():
        addresses.extend(sorted(set(x[4][0] for x in socket.getaddrinfo(HOST,443,type=socket.SOCK_STREAM))))
        return {'응답주소': addresses}
    results.append(probe('API 서버 DNS', dns))
    results.append(probe('API 서버 TCP 443(호스트명)', lambda: tcp(HOST,443)))
    for addr in addresses:
        results.append(probe('API 서버 TCP 443(IP 직접) '+addr, lambda: tcp(addr,443)))
    results.append(probe('API 서버 TLS 핸드셰이크', tls))
    results.append(probe('API 서버 HTTPS(프록시 미사용)', lambda: https(False)))
    results.append(probe('API 서버 HTTPS(현재 프록시 설정)', lambda: https(True)))
    results.append(probe('대조군 example.com TCP 443', lambda: tcp('example.com',443)))
    proxies = urllib.request.getproxies()
    proxy_summary = {'설정된종류': sorted(proxies), '프록시주소와인증정보': '미기록'}
    for scheme in ('https', 'http'):
        value = proxies.get(scheme)
        if value:
            parsed = urllib.parse.urlsplit(value if '://' in value else 'http://'+value)
            if parsed.hostname:
                results.append(probe('설정된 '+scheme+' 프록시 TCP', lambda: tcp(parsed.hostname, parsed.port or 80)))
    env_summary = {name: bool(os.environ.get(name)) for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY')}
    # 원본을 변경하지 않고 stdout/stderr를 메모리에서 폐기한다.
    # 기본 환경의 의존성 상태도 숨김 없이 결과에 구분한다.
    original = {'파일': 'bus_api_test.py', 'requests설치': bool(importlib.util.find_spec('requests')),
                'python_dotenv설치': bool(importlib.util.find_spec('dotenv'))}
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(ROOT/'bus_api_test.py'), run_name='__main__')
        original['상태'] = '실행 종료(원본은 예외를 내부 처리하므로 API 성공을 뜻하지 않음)'
    except BaseException as exc:
        original['상태'] = '실행 실패'
        original['오류유형'] = type(exc).__name__
        if isinstance(exc, ModuleNotFoundError) and exc.name == 'dotenv':
            original['원인'] = '현재 Python에 python-dotenv 미설치: API 호출 전 import에서 중단'
    spec = importlib.util.spec_from_file_location('tram_diag', ROOT/'diagnose_tram_105_106.py')
    diag = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(diag)
    # 기존 진단 모듈은 dotenv 외부 패키지 없이 .env를 안전하게 읽는다.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        diag.main()
    collection = sorted(ROOT.glob('diagnostics_105_106_*'))[-1]
    import csv
    with (collection/'정거장별_진단요약.csv').open(encoding='utf-8-sig') as f:
        collected = list(csv.DictReader(f))
    report = {'검사시각': datetime.now().isoformat(), 'Python실행파일': __import__('sys').executable,
              '네트워크검사': results, '프록시': proxy_summary, '프록시환경변수설정여부': env_summary,
              '원본스크립트검사': original, '재수집결과폴더': str(collection),
              '원본Python_CSV_Excel해시동일': before == hashes()}
    (RESULT/'네트워크_검사결과.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['공공데이터 API 네트워크 진단', '실행 Python: '+report['Python실행파일'], '']
    for r in results:
        lines.append(json.dumps(r, ensure_ascii=False))
    lines.extend(['', '프록시: '+json.dumps(proxy_summary,ensure_ascii=False),
                  '기존 bus_api_test.py: '+json.dumps(original,ensure_ascii=False), '',
                  '판정 방법:',
                  '- DNS 성공이면 이름 해석 실패가 이번 연결 실패의 직접 원인은 아니다.',
                  '- 프록시를 끈 IP 직접 TCP도 10013이면 프록시만의 문제로 설명되지 않는다.',
                  '- OS 10013은 소켓 접근 권한 거부다. 인증키 검증이나 HTTP 응답 이전 단계의 오류다.',
                  '- Windows 방화벽, 보안 프로그램/EDR, 실행 환경의 네트워크 권한 제한은 이 결과만으로 구별 확정할 수 없다.',
                  '- 방화벽/보안 설정은 변경하지 않았다. 규칙이나 차단 이벤트를 확인하지 못하면 Windows 방화벽 탓으로 단정할 수 없다.',
                  '- python-dotenv 누락은 기존 테스트의 별도 실행 문제다. 패키지 설치만으로 소켓 접근 거부가 해결되지는 않는다.', '',
                  '105/106 재수집:'])
    for s in collected:
        lines.append('{}번: 상태={}, 진단={}, 실패원인={}'.format(s['트램정거장번호'],s['API상태'],s['진단'],s['실패원인']))
    lines.extend(['재수집 결과 폴더: '+str(collection),
                  '연결 실패 시 건수는 관측된 수집 건수이며 API가 정상 응답한 0건이 아니다.',
                  '300m 기준 유지: d≤300 / 300<d≤500 / d>500. 좌표 오류 별도.',
                  '원본 Python/CSV/Excel 해시 동일: '+str(report['원본Python_CSV_Excel해시동일'])])
    (RESULT/'네트워크_진단_한국어요약.txt').write_text('\n'.join(lines),encoding='utf-8-sig')
    print('\n'.join(lines))
    print('네트워크 결과 폴더: '+str(RESULT))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('진단 실행 중 오류: '+type(exc).__name__+' (인증정보 보호를 위해 예외 본문 생략)')
        raise SystemExit(1)

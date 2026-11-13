# GITS · V-World 매칭 후보 지도

이 지도는 ID가 일치하는 교통정보의 위치와 매칭 상태를 검토한다. 실제 혼잡도를 확정하거나 DRT 배차·경로 비용에 적용하지 않는다. 모든 후보의 최종 상태는 `review_required`이다.

현재 메뉴 통합 버전에서는 **통합 대시보드 → 교통정보 상세 보기 → GITS 후보 지도**에서 생성된 HTML을 볼 수 있다. 기존 속도표·그래프·품질표는 **GITS 상세 분석**에서 접근한다. 아래의 최초 연동 제안은 설계 참고용이며 실제 연결 구조는 `menu_integration_usage.md`를 따른다.

## 실행

프로젝트 최상위에서 실행한다. 스크립트 자체는 다른 작업 디렉터리에서도 실행할 수 있다.

```powershell
python -B drt_system/scripts/build_gits_vworld_map.py
python -B -m unittest discover -s drt_system/tests -p test_gits_vworld_map.py -v
```

필요 패키지: 기존 환경의 `folium`, `pyproj`. 실행마다 `data/derived/gits_vworld/<UTC시각_UUID>/`를 새로 만든다. 기존 결과와 원본을 덮어쓰지 않는다.

## 산출물

- `matching_candidates.csv`: 후보 16행. 길이·속도·시간·환산 길이·차이율·시각 의미·출처·기존 결과 일치 여부.
- `unmatched_gits.csv`: 미매칭 44행. 원래 요약 필드를 보존한다.
- `vworld_with_gits.geojson`: 원본 3,221개 형상과 속성을 유지하며 `gits_observations` 등에 검토 정보를 추가한다.
- `gits_vworld_review_map.html`: 회색 미관측 3,205개, 파랑 저오차 8개, 주황 고오차 8개. 레이어 제어와 클릭 팝업 포함.
- `matching_summary.json`: 건수, 출처, 입력 경로·SHA-256, 계산 방법, CRS 가정, 제한사항.

GeoJSON은 명시적 CRS가 없어 WGS84 경위도로 가정한다. 길이는 WGS84 타원체 측지거리다. 환산 길이는 평균속도 × 평균 통행시간 ÷ 3.6이며 차이율 분모는 도형 길이다. 10% 이하는 `candidate_low_error`, 초과는 `candidate_high_error`, 계산 불가는 `candidate_missing_length`로 표시한다. 계산 불가 후보가 생기면 보라색이다.

현재 일치 후보의 시각은 원본 이력 CSV의 수집 시각에서 유래한다. 측정 시각으로 확정하지 않는다. 지도는 `tiles=None`으로 생성해 배경 타일을 요청하지 않는다. Leaflet JS/CSS 등 Folium의 CDN 리소스에는 인터넷이 필요하므로 완전한 오프라인 파일은 아니다. 평균속도는 팝업으로 제공하며 속도 기반 색상 레이어는 이번 구현에서 추가하지 않았다.

## 향후 Streamlit 연동 제안 (아직 적용하지 않음)

`drt_system/app.py` 39행의 사이드바 메뉴 목록과 621행의 도로 혼잡도 분석 분기를 확인했다. 기존 621~623행은 `modules.gits_views.show_roads()`를 호출한다. 기존 분기를 유지하고, 승인 후 사이드바 목록에 `GITS 교통정보 분석`을 추가하고 독립적인 `elif` 분기를 만드는 방식을 권장한다.

새 `modules/gits_review_views.py`의 `show_gits_review()`에서 실행 결과를 선택하고, 아래 코드를 사용해 지도를 임베딩할 수 있다. 먼저 산출물을 생성하고, 선택한 실행 폴더에서 HTML을 읽는다. 앱 실행마다 분석을 재생성하지 않는다. 이 모듈 및 app.py 변경은 아직 적용하지 않았다.

```python
from pathlib import Path
import streamlit.components.v1 as components

runs = sorted((PROJECT_DIR / "data/derived/gits_vworld").glob("*/gits_vworld_review_map.html"), reverse=True)
if runs:
    selected = st.selectbox("매칭 검토 결과", runs, format_func=lambda p: p.parent.name)
    st.caption("매칭 후보 검토용 · 모든 후보 review_required · 실제 혼잡도 확정 아님")
    components.html(selected.read_text(encoding="utf-8"), height=760, scrolling=True)
else:
    st.info("별도 지도 생성 스크립트를 먼저 실행하세요.")
```

예약·배차·경로 모듈과 연결하지 않는다. 독립적인 링크 형상·시종점·방향 증거가 확보되기 전에는 운행시간에 적용하지 않는다.

새 화면에는 `matching_summary.json`의 전체 도로/매칭 후보/미매칭/검증 완료(현재 0) 통계, 지도, `matching_candidates.csv`의 링크별 속도·시간·길이 오차·검증 상태, `unmatched_gits.csv`의 미매칭 표를 별도 탭으로 제공한다. 출처와 수집 시각은 표 및 팝업에서 보여주며 `as_of`나 생성 시각을 실제 측정 시각으로 표시하지 않는다. 링크 ID는 `dtype=str`로 읽는다. 모든 파일을 동일 실행 폴더에서 읽어 실행 결과가 섞이지 않게 한다.

## 타일 오류 원인과 수정

- 원래 지도는 `tiles="OpenStreetMap"`을 사용했다. 사용자가 보고한 403의 구체적 차단 사유는 당시 HTTP 요청/응답 증거가 없어 확정하지 못했다.
- OSM 공식 정책은 웹 요청의 유효한 Referer 등 식별·캐시 조건을 요구한다. 로컬 `file://` 실행의 Referer 부재나 실행 환경의 요청 처리와 관련됐을 가능성은 추정이며, 차단 원인으로 단정하지 않는다. 정책: https://operations.osmfoundation.org/policies/tiles/
- `20261113T051822Z_d582e513/gits_vworld_review_map_fixed.html`은 약 3.5KB이며 `L.geoJson`과 팝업 코드가 전혀 없다. 배경 제거 후 도로가 안 보이는 직접 원인은 도로 생성 코드도 없어진 것이다. 어떤 편집 명령이 이를 삭제했는지는 확인하지 못했다.
- `gits_map_rebuilt.html`은 존재한다. 약 7MB이며 3,221개 GeoJSON 레이어·팝업이 있지만 이 파일은 수정하지 않았다.
- 수정 모듈은 처음부터 `tiles=None`으로 생성하며 원본 좌표에서 중심과 `fit_bounds`를 계산한다. 밝은 배경과 회색 도로의 대비를 높이고 Canvas 렌더링을 사용한다. 배경 타일과 도로 레이어가 독립적이므로 타일 서버 없이 도로를 그린다.
- 임의의 무료 타일 서버로 교체하거나 User-Agent/Referer를 위조하지 않는다. 대체 배경은 향후 이용 권한과 출처 표기가 확보된 자체 호스팅 타일 또는 계약된 제공자만 선택 옵션으로 추가한다. 기본값은 계속 배경 없음으로 유지한다.

## 검증 범위

수정 후 자동 테스트 6개 통과: 원본 보존·매칭 분리, 문자열 ID/결측/오차 경계, 팝업 필드, 실제 좌표 기반 범위, 타일 없는 지도 트리의 3,221개 도로와 색상 수량, Node.js의 생성 JavaScript 문법 검사.

확대 제어·fitBounds·레이어 제어·팝업 바인딩은 생성 코드에서 확인했다. 브라우저 도구가 `The browser access host is unavailable`을 반환하여 실제 화면 렌더링, 확대/축소와 레이어 토글·팝업 클릭, 브라우저 콘솔 오류 유무는 미검증이다. JavaScript 문법 검사 통과는 브라우저 실행 무오류를 의미하지 않는다.

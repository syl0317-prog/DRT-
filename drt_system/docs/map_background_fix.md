# 두 운영 지도 배경 복구

## 확인한 원인

통합 대시보드는 `dashboard_views.overview_map()`, 배차·경로 지도는 `route_views.show_drt_map()`을 호출한다. 원래 팀원 파일 `map_view.py`는 현재 라우터가 직접 호출하지 않는다. 두 활성 지도에 `tiles=None`이 설정되어 타일 요청 자체가 없었다. 마커와 확대 버튼이 표시되는 상황은 Leaflet의 지도 초기화·오버레이는 동작하지만 배경이 제거된 상태와 일치한다. 메뉴 통합 때 적용한 타일 제거 설정이 직접 원인이다.

과거 OSM 403은 당시 브라우저 요청 헤더와 응답 증거가 없어 정확한 이유를 확정할 수 없다. 이번 진단에서는 위례 중심에 해당하는 확대 14 타일을 제공자별 1회 요청했다. 식별 가능한 진단 프로그램 User-Agent를 사용했고 브라우저나 Referer를 위조하지 않았다.

| 진단 URL | 응답 | 본문 |
|---|---|---|
| `https://tile.openstreetmap.org/14/13978/6350.png` | 200 | image/png, 32,831 bytes, PNG 서명 확인 |
| `https://tile.openstreetmap.de/14/13978/6350.png` | 200 | image/png, 32,217 bytes, PNG 서명 확인 |

초기 샌드박스 요청은 WinError 10013으로 연결이 차단됐다. 허용된 샌드박스 밖 진단에서 위 결과를 확인했다. 이는 서버 측 진단 결과이며 사용자의 브라우저 표시·접속 제한을 보장하지 않는다.

## 최소 수정

- 새 `map_background.py`에서 명시적인 HTTPS URL·출처 표기·로딩 안내를 공유한다.
- 기본: OpenStreetMap 표준. 대체 선택: OSM Deutschland/FOSSGIS. 두 서비스 모두 API 키를 연결하지 않는다.
- Folium Map 생성 시 실제 기본 TileLayer를 전달한다. 타일 없는 모드로 오류를 숨기지 않는다.
- 대체 레이어는 처음에는 비활성이다. 사용자 선택 시에만 해당 제공자의 타일을 요청한다. 자동 순환·프록시·재시도 루프·일괄 다운로드는 없다.
- `strict-origin-when-cross-origin`을 명시하고 실제 브라우저의 Referer 처리를 사용한다. 신원·헤더를 위조하지 않는다.
- 실제 `tileerror`에 실패 안내를 표시하고, 15초 동안 타일이 로딩되지 않으면 지연 안내를 표시한다. HTTP 403인지 여부를 브라우저 이미지 이벤트만으로 단정하지 않는다.
- 기본 중심·확대·fitBounds, 모든 마커, 경유지 선택·OSRM 호출·경로 선·클릭 좌표 처리 및 6개 메뉴는 유지한다.

온라인 배경은 제공자가 서비스하는 지도 이미지다. V-World GeoJSON은 별도의 도로 벡터 오버레이이며 배경지도·건물 데이터를 대체하지 않는다. GITS 검토 지도 생성 코드는 이번 변경 대상이 아니다.

## 이용 정책

- OSM 표준: https://operations.osmfoundation.org/policies/tiles/ — 올바른 URL, 출처 표기, 식별/Referer, 캐시 규칙 준수. 서비스 가용성 보장은 없다.
- OSM Deutschland: https://openstreetmap.de/germanstyle/ 및 https://www.openstreetmap.de/nutzen/dienste-osm-de/ — 등록 없이 전세계 지도를 제공하고, 비상업용 웹 임베딩을 허용하며 대량 다운로드를 제한한다. 이 프로젝트의 연구·캡스톤 웹 시연을 위한 대체 선택이다. 운영·상업 용도 확대 시 이용 범위를 다시 확인한다.
- CARTO는 현재 공식 문서상 API 키가 필요하므로 임의로 연결하지 않았다: https://docs.carto.com/faqs/carto-basemaps

## 검증

전체 회귀 테스트 59개가 통과했다. 기존 데이터 95개 파일의 SHA-256은 변경되지 않았다. 상세 결과는 `map_background_validation.json`에 기록했다.

`test_map_background.py`의 4개 테스트로 기본/대체 타일 설정·출처·Referrer 정책, 마커 6개(환승 2, DRT 4), 경로 미호출 대시보드, 상세 지도 경로 선·클릭 상태, JavaScript 문법 및 실패/복구/지연 안내의 모의 이벤트 동작을 검사한다. 네트워크 요청을 반복하는 자동 테스트는 추가하지 않았다.

브라우저 도구는 `The browser access host is unavailable`을 반환했다. 실제 브라우저의 배경 도로·건물 표시, 확대/축소, 제공자 전환, 클릭 이벤트와 콘솔 오류는 미검증이다. 자동 테스트의 모의 이벤트 성공과 실제 브라우저 검증을 구분한다.

기존 Streamlit을 재실행하고 두 지도에서 배경을 확인한다. 실패 시 지도 오른쪽 위 레이어에서 대체 제공자를 선택하고 브라우저 개발자 도구 Network의 타일 URL·상태코드·응답을 확인한다. 출처 표기는 지도에 유지한다.

```powershell
python -B -m streamlit run drt_system/app.py
```

"""Local data provenance inventory; no network probes or source mutations."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st
from modules.settings import PROJECT_DIR


def data_inventory():
    rows=[]
    groups=[('sewook31/data', '운영 원본 및 보관 OSRM', '예약·지도'),
            ('data/seeds', '복구용 연구 노선', '최초 초기화'),
            ('data/derived/drt_routes', '연구 노선 등록부', 'R02·차량·구간'),
            ('data/derived/unified_reservations', 'SQLite 접수 및 취소 오버레이', '통합 예약'),
            ('data/processed', '가공 결과·관측/가정 혼합', '교통·정시성·시뮬레이션 분석'),
            ('data/assumptions', '가정·참조자료（실측 보장 없음）', '모형 입력'),
            ('data/vworld', '저장 도로 GIS', '지도·도로 검증'),
            ('data/derived/gits_vworld', 'GITS 매칭 후보·검토 필요', '교통 검토 지도'),
            ('data/raw', '수집 원본·관측 시점은 출처별 확인 필요', '분석 입력'),
            ('drt_system/data', '이전 앱 별도 사본', '메인 앱 미사용·자동 병합 안 함')]
    for folder,kind,usage in groups:
        base=PROJECT_DIR/folder
        for p in sorted(base.rglob('*')) if base.exists() else []:
            if not p.is_file() or p.suffix.lower() in ('.pyc', '-wal', '-shm'):
                continue
            stat=p.stat()
            rows.append({'파일':str(p.relative_to(PROJECT_DIR)), '분류':kind, '활용':usage,
                '수정 시각 UTC':datetime.fromtimestamp(stat.st_mtime,timezone.utc).isoformat(),
                '크기 bytes':stat.st_size, '품질/시점':'파일 수정 시각은 관측 시각이 아님; 출처 메타데이터 확인'})
    return rows


def _show_data_status():
    from modules.unified_reservations import UnifiedReservations
    from modules.fixed_routes import resolve_stop
    st.caption('읽기 전용 로컬 상태 · 파일 수정 시각은 관측 시각과 다릅니다.')
    service=UnifiedReservations()
    try:
        state=service.routes.snapshot(); catalog=service.catalog()
        checks=[]
        for stop in catalog['boarding']:
            try:
                rid,target=resolve_stop(service.routes.original_loader(),state,stop['stop_id'])
                checks.append({'정류장':stop['stop_id'],'노선':rid,'고정 목적지':target,'검증':'정상'})
            except ValueError as error:
                checks.append({'정류장':stop['stop_id'],'검증':str(error)})
        st.dataframe(pd.DataFrame(checks),hide_index=True)
        for path in (service.routes.path,service.path):
            if not path.exists():
                st.info(f'{path.name}: 아직 생성되지 않음')
                continue
            # URI read-only mode guarantees inspection cannot initialize/alter a DB.
            with sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True) as connection:
                status=connection.execute('PRAGMA quick_check').fetchone()[0]
            st.write(f'{path.relative_to(PROJECT_DIR)} · SQLite quick_check: {status}')
        records=service.list_records()
        invalid=[r['public_id'] for r in records if r.get('route_id') in ('R01','R02') and r.get('destination_stop') != {'R01':'T01','R02':'T02'}[r['route_id']]]
        if invalid:
            st.warning(f'고정 목적지 정책과 다른 과거 예약 {len(invalid)}건. 원본을 자동 변경하지 않습니다.')
        st.info('API 상태: 이번 화면에서 연결 검사하지 않음. TOPIS/GITS 저장 자료는 실시간 교통정보가 아닙니다.')
        st.warning('R02 원본은 T02 연결 미등록 상태일 수 있습니다. 목적지 자동 지정과 실제 도로 연결·차량 배정은 별도 검증합니다.')
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        st.error(f'데이터 검증 실패: {error}')
    rows=data_inventory()
    st.subheader('데이터 파일 및 활용 목록')
    st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch',height=380)
    st.download_button('파일 목록 CSV 다운로드',pd.DataFrame(rows).to_csv(index=False).encode('utf-8-sig'),file_name='drt_data_inventory.csv')


def show_system():
    from modules.session_ui import scope
    from modules.reservation_audit import audit_service,audit_summary,display_rows
    from modules.unified_reservations import UnifiedReservations
    st.subheader('데이터 및 시스템 관리')
    audit_tab,registry_tab,data_tab=st.tabs(['예약 데이터 검증','원본 R02 연구용 등록부','데이터·DB 상태'])
    with audit_tab:
        try:
            service=UnifiedReservations();rows=audit_service(service);summary=audit_summary(rows)
            cols=st.columns(3)
            cols[0].metric('과거 CSV',summary['history']);cols[1].metric('규칙 불일치',summary['mismatches']);cols[2].metric('연구·시험',summary['research'])
            invalid=[r for r in rows if not r['policy_valid']]
            if invalid:
                st.warning('고정 노선 규칙과 다른 기록입니다. 원본과 원본 상태는 변경하지 않습니다.')
                st.dataframe(pd.DataFrame(display_rows(invalid)),hide_index=True,width='stretch',height=240)
            else:
                st.success('노선·목적지 규칙 불일치 없음')
            with st.expander('과거·신규·시험 분류 기준'):
                st.write('CSV는 과거 기록, 등록부 예약은 연구 기록으로 분리합니다. 신규 SQLite의 등록 운영 운행편만 운영 배정으로 표시합니다. 시험 운행편과 규칙 불일치는 운영 지표에서 제외합니다.')
        except (OSError,ValueError,KeyError,sqlite3.Error) as error:
            st.error(f'예약 데이터 검증 실패: {error}')
    with registry_tab:
        st.caption('원본 연구용 등록부 · 실제 차량·운행편 등록과 별개')
        from modules.independent_route_views import show_route_summary,show_route_management
        from modules.independent_routes import RouteStore
        try:
            show_route_summary(RouteStore().snapshot())
            with st.expander('기존 연구 등록부 관리 도구'):
                with scope('system_research_registry'):
                    show_route_management()
        except (OSError,ValueError,KeyError,sqlite3.Error) as error:
            st.error(f'연구 등록부 조회 실패: {error}')
    with data_tab:
        _show_data_status()

"""Compact operating dashboard; archive/research data never count as live ops."""
import sqlite3
import pandas as pd
import streamlit as st
from modules.unified_reservations import UnifiedReservations
from modules.reservation_audit import audit_service,audit_summary,display_rows
from modules.sequential_routes import route_plans
from modules.settings import stops_path,setting


def show_policy_warning(rows,key='policy'):
    invalid=[r for r in rows if not r['policy_valid']]
    if invalid:
        active=sum(r.get('status') in ('예약완료','배차 검토 필요') for r in invalid)
        st.warning(f'노선 규칙 불일치 {len(invalid)}건 (유효 상태 {active}건) · 운영 집계 제외 · 원본 보존')
        with st.expander('불일치 기록 확인'):
            st.dataframe(pd.DataFrame(display_rows(invalid)),hide_index=True,width='stretch',height=190)
    return invalid


def show_operating_dashboard(research_renderer):
    from modules.dashboard_views import overview_map,navigate,reservation_snapshot
    from modules.unified_reservation_views import records_frame
    st.subheader('통합 대시보드')
    service=UnifiedReservations()
    try:
        rows=audit_service(service);summary=audit_summary(rows)
        state=service.routes.snapshot();ops=service.operations()
        plans=route_plans(service.routes.original_loader(),state)
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        st.error(f'운영 자료 조회 실패: {error}');return
    fleet=[v for v in ops['vehicles'] if not v['test_only'] and v['available']]
    values=[summary['operating'],summary['pending'],summary['confirmed'],len(fleet),'데이터 없음']
    for col,label,value in zip(st.columns(5),['신규 유효 접수','배차 대기','배차 확정','등록 운영 차량','실제 운행 차량'],values):
        col.metric(label,value)
    st.caption(f"신규 유효 접수 기준 · 과거 CSV {summary['history']}건 / 연구·시험 {summary['research']}건 별도 · 배차 확정은 실제 운행 개시와 다릅니다.")
    show_policy_warning(rows,'dashboard')
    operating,research=st.tabs(['운영 현황','연구·모형 결과'])
    with operating:
        left,right=st.columns([1.4,1],gap='medium')
        with left:
            st.markdown('**고정 노선 지도**')
            try:
                stops=pd.read_csv(stops_path(),encoding='utf-8-sig')
                st.iframe(overview_map(stops,state),height=450)
                st.caption('R01 파랑 · R02 주황 · 번호: 경유 순서 · 점선: 미검증 구간')
            except (OSError,ValueError,KeyError) as error:
                st.warning(f'지도 조회 실패: {error}')
        with right:
            route_tab,recent_tab,alerts_tab=st.tabs(['노선·배차','최근 접수','확인 사항'])
            with route_tab:
                route_rows=[]
                for p in plans:
                    current=[r for r in rows if r['operating_record'] and r['route_id']==p['route_id']]
                    runs=[r for r in ops['runs'] if r['route_id']==p['route_id'] and r['active'] and not r['test_only']]
                    route_rows.append({'노선':p['route_id'],'대기':sum(r['display_stage']=='예약 접수 · 배차 대기' for r in current),
                        '확정':sum(r['display_stage']=='배차 확정' for r in current),'등록 운행편':len(runs),
                        '상태':'도로 구간 확인 필요' if not p['road_complete'] else '운행편 등록됨' if runs else '운행편 없음'})
                st.dataframe(pd.DataFrame(route_rows),hide_index=True,width='stretch')
                st.caption('차량 위치·실제 운행 중 상태는 수집 자료가 없습니다.')
                st.button('예약·배차 관리',on_click=navigate,args=('예약 및 배차 관리',),key='dashboard_booking_link')
                st.button('차량·운행편 관리',on_click=navigate,args=('노선 및 운영 관리',),key='dashboard_operations_link')
            with recent_tab:
                current=[r for r in rows if r['operating_record']][-8:]
                if current:
                    df=pd.DataFrame(display_rows(current))
                    st.dataframe(df[['노선','승차','하차','인원','표시 상태']],hide_index=True,width='stretch',height=275)
                else:
                    st.info('신규 운영 접수 없음. 과거 기록은 예약 목록에서 확인하세요.')
            with alerts_tab:
                pending=[r for r in rows if r['operating_record'] and r.get('status')=='배차 검토 필요']
                if pending:
                    counts=pd.Series([r['review_reason'] for r in pending]).value_counts().rename_axis('대기 사유').reset_index(name='건수')
                    st.dataframe(counts,hide_index=True,width='stretch')
                else:
                    st.caption('신규 접수의 배차 대기 없음')
                for p in plans:
                    if not p['road_complete']:
                        st.warning(f"{p['route_id']} 최종 트램 연결 구간 검증 필요")
                st.caption('과거 기록의 규칙 불일치는 상단 경고에서 확인하세요.')
        with st.expander('집계 기준'):
            st.write('접수·대기는 규칙에 맞는 신규 SQLite 기록만 집계합니다. 배차 확정은 등록 차량·운행편의 운영 배정만 포함합니다. 과거·연구·시험·규칙 불일치 기록은 운영 지표에서 제외하며 삭제하지 않습니다.')
    with research:
        st.info('연구·시뮬레이션 자료입니다. 운영 실적에 포함하지 않습니다.')
        count=st.session_state.get('vehicle_count',setting('vehicle_count'))
        research_renderer(count,reservation_snapshot(records_frame(rows),count))

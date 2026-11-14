"""Fixed-route stop loads and explicit fleet/run setup, separate from simulations."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
import streamlit as st
from modules.session_ui import persistent_ui as ui
from modules.unified_reservations import UnifiedReservations
from modules.sequential_routes import route_plans
from modules.fixed_dispatch import register_vehicle,register_run,boarding_at
from modules.independent_routes import RouteError

KST=ZoneInfo('Asia/Seoul')


def dispatch_tables(service,run_id=None,data_scope="all"):
    plans=route_plans(service.routes.original_loader(),service.routes.snapshot())
    from modules.reservation_audit import audit_service
    audited=audit_service(service)
    records=[r for r in audited if r['policy_valid']]
    if data_scope=='operating':
        records=[r for r in records if r['operating_record']]
    elif data_scope=='research':
        records=[r for r in records if r['data_category'] in ('연구 등록부','시험 운행편','과거 연구 배정')]
    ops=service.operations()

    dated=[r for r in records if r.get('requested_at') and (run_id is None or r.get('run_id')==run_id or r.get('requested_run_id')==run_id)]
    stops=[];runs=[]
    for plan in plans:
        for position,stop in enumerate(plan['stops'],1):
            own=[r for r in dated if r['route_id']==plan['route_id'] and r['boarding_stop']==stop['stop_id']]
            stops.append(dict(노선=plan['route_id'],순서=position,정류장=stop['stop_id'],구분='최종 하차' if position==len(plan['stops']) else '승차',
                배정_승객=sum(r['passengers'] for r in own if r['status']=='예약완료'),
                대기_승객=sum(r['passengers'] for r in own if r['status']=='배차 검토 필요'),
                하차_예정=sum(r['passengers'] for r in dated if r['route_id']==plan['route_id'] and r['status']=='예약완료') if position==len(plan['stops']) else 0))
    for run in ops['runs']:
        if data_scope=='operating' and run['test_only']:continue
        if data_scope=='research' and not run['test_only']:continue
        if run_id is not None and run['run_id']!=run_id:
            continue
        own=[r for r in records if r.get('run_id')==run['run_id'] and r['status']=='예약완료']
        waiting=[r for r in records if r.get('requested_run_id')==run['run_id'] and r['status']=='배차 검토 필요']
        current_plan=next(p for p in plans if p['route_id']==run['route_id'])
        runs.append(dict(운행편=run['run_id'],노선=run['route_id'],차량=run['vehicle_id'],출발=datetime.fromisoformat(run['departure']).astimezone(KST).isoformat(),
            정원=run['capacity'],탑승예정=sum(r['passengers'] for r in own),배차완료=len(own),배차대기=len(waiting),
            최종목적지=run['order'][-1],구분='테스트' if run['test_only'] else '운영 등록',실제운행상태='데이터 없음',
            경로상태='등록 경로 일치' if run['route_signature']==current_plan['signature'] else '경로 변경 · 재검토 필요'))
    return dict(stops=stops,runs=runs,invalid=sum(not r['policy_valid'] for r in audited),undated=sum(not r.get('requested_at') for r in audited),
        assigned=sum(r['status']=='예약완료' for r in dated),pending=sum(r['status']=='배차 검토 필요' for r in dated))


def show_dispatch_board(compact=False):
    from modules.dispatch_board_ui import render_dispatch_board
    render_dispatch_board(UnifiedReservations(),dispatch_tables,compact)


def show_fixed_operations():
    st.subheader('고정 노선 차량·운행편 등록')
    st.caption('실제 확인된 차량과 날짜별 운행편만 입력하세요. 기존 연구용 차량 슬라이더나 R02 후보 차량을 실제 차량으로 자동 사용하지 않습니다.')
    service=UnifiedReservations()
    try:
        ops=service.operations()
        st.dataframe(pd.DataFrame([{'차량':v['vehicle_id'],'정원':v['capacity'],'가용':v['available'],'구분':'시험' if v['test_only'] else '운영 등록'} for v in ops['vehicles']]),hide_index=True,width='stretch')
        with st.form('fixed_vehicle_form'):
            vehicle_id=st.text_input('실제 차량 ID',key='fixed_vehicle_id')
            capacity=st.number_input('확인된 차량 정원',1,100,8,key='fixed_capacity')
            evidence=st.text_input('차량 확인 근거',key='fixed_vehicle_evidence')
            confirmed=st.checkbox('실재하고 운영 가능한 차량임을 확인했습니다',key='fixed_vehicle_confirmed')
            if st.form_submit_button('확인 차량 등록'):
                if not confirmed:
                    raise RouteError('실제 차량 확인 후 등록하세요.')
                register_vehicle(service,vehicle_id,int(capacity),evidence)
                st.success('새 차량 등록 완료. 기존 CSV·노선 등록부는 변경하지 않았습니다.')
                st.rerun()
        operational_vehicles=[v for v in ops['vehicles'] if not v['test_only'] and v['available']]
        if not operational_vehicles:
            st.info('운영 차량 데이터 없음. 차량을 임의 생성하지 않습니다.')
            return
        with st.form('fixed_run_form'):
            rid=st.selectbox('운행 노선',['R01','R02'],key='fixed_run_route')
            vid=st.selectbox('운행 차량',[v['vehicle_id'] for v in operational_vehicles],key='fixed_run_vehicle')
            future=datetime.now(KST)+timedelta(days=1)
            day=st.date_input('운행 날짜',future.date(),key='fixed_run_day')
            clock=st.time_input('첫 정류장 출발 시각',future.time().replace(second=0,microsecond=0,tzinfo=None),key='fixed_run_clock')
            offsets_text=st.text_input('고정 순서 5개 지점의 예정 분 (첫 지점 0, 쉼표 구분)',placeholder='확인된 시간표를 입력하세요',key='fixed_run_offsets')
            access=st.text_input('고정 경로 운행·정류장 접근 및 정차 가능 확인 근거',key='fixed_access_evidence')
            st.caption('R01 D01→D02→D03→D04→T01 / R02는 저장된 방문 순서→T02. 회차·공차 이동 여유도 운영자가 확보해야 합니다.')
            if st.form_submit_button('날짜별 운행편 등록'):
                plan=next(p for p in route_plans(service.routes.original_loader(),service.routes.snapshot()) if p['route_id']==rid)
                values=[float(x.strip()) for x in offsets_text.split(',')]
                if len(values)!=len(plan['order']):
                    raise RouteError('승차 정류장 4개와 최종 트램 지점의 예정 분 5개가 필요합니다.')
                register_run(service,rid,vid,datetime.combine(day,clock,KST),dict(zip(plan['order'],values)),access)
                st.success('운행편 등록 완료');st.rerun()
        show_dispatch_board()
    except (RouteError,OSError,ValueError,KeyError,sqlite3.Error) as error:
        st.error(f'운영 등록 실패: {error}')

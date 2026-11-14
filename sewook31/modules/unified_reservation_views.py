"""Single stop-first booking screen and supported simulation adapters."""
from datetime import datetime,timedelta
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as streamlit
from modules.session_ui import persistent_ui as st, signature
from modules.unified_reservations import UnifiedReservations, ACTIVE
from modules.independent_routes import RouteError, booking_schedule

KST=ZoneInfo("Asia/Seoul")


def records_frame(records):
    return pd.DataFrame(records,columns=["public_id","boarding_stop","destination_stop","requested_at","time_basis",
        "tram_departure","passengers","status","route_id","vehicle_id","dispatch_status","source","simulation_adapter"])


def show_booking_form():
    streamlit.subheader("예약 접수")
    streamlit.caption("승차 정류장 → 노선·목적지 자동 지정 · 접수와 배차 확정은 구분됩니다.")
    service=UnifiedReservations()
    try:
        catalog=service.catalog()
        stops=catalog["boarding"]
        lookup={s["stop_id"]:s for s in stops+catalog["trams"]}
        ids=[s["stop_id"] for s in stops]
        if len(stops)!=8:
            streamlit.warning(f"현재 저장된 DRT 정류장은 {len(stops)}개입니다. 미등록·잘못된 정류장 이름이나 좌표는 임의로 채우지 않습니다.")
        if len(stops)<2:
            raise RouteError("예약 가능한 저장 정류장이 부족합니다.")
        label=lambda key:f"{lookup[key]['name']} ({key})"
        left,right=streamlit.columns(2)
        with left:
            origin=st.selectbox("탑승 정류장",ids,format_func=label,key="ua_origin")
        from modules.fixed_routes import resolve_stop
        route_id,destination=resolve_stop(service.routes.original_loader(),service.routes.snapshot(),origin)
        with right:
            streamlit.info(f"{route_id} → {label(destination)} · 고정 목적지")
        if route_id == "R02":
            route=next((r for r in service.routes.snapshot()["routes"] if r["route_id"]=="R02"),None)
            if not route or not route["active"] or not route["vehicles"] or route.get("transfer_stop_id") != destination:
                streamlit.warning("R02 경로·운행 조건 확인 전까지 배차 대기로 접수합니다.")
        future=datetime.now(KST)+timedelta(hours=1)
        left,right=streamlit.columns(2)
        with left:
            day=st.date_input("탑승 희망 날짜",future.date(),key="ua_day")
        with right:
            clock=st.time_input("탑승 희망 시간 (한국시간)",future.time().replace(second=0,microsecond=0,tzinfo=None),key="ua_time")
        passenger_col,run_col=streamlit.columns([.65,1.35])
        with passenger_col:
            passengers=st.number_input("탑승 인원",1,100,1,key="ua_passengers")
        online=False
        request_time=datetime.combine(day,clock,KST)
        from modules.fixed_dispatch import boarding_at
        runs=[r for r in service.operations()['runs'] if r['route_id']==route_id and r['active'] and datetime.fromisoformat(r['departure'])>datetime.now(KST)]
        run_lookup={r['run_id']:r for r in runs}
        with run_col:
            run_id=st.selectbox('등록 운행편',[None]+list(run_lookup),
                format_func=lambda k:'미선택 · 검토 접수' if k is None else f"{run_lookup[k]['vehicle_id']} · {boarding_at(run_lookup[k],origin).astimezone(KST):%m/%d %H:%M} 승차"+(' · 시험' if run_lookup[k]['test_only'] else ''),key='ua_run')
        if run_id:
            request_time=boarding_at(run_lookup[run_id],origin).astimezone(KST)
            streamlit.info(f'선택 운행편의 {origin} 예정 승차 시각 {request_time:%Y-%m-%d %H:%M:%S}을 적용합니다. 정류장 방문 순서는 고정됩니다.')
        tram_departure=None
        if destination in {s["stop_id"] for s in catalog["trams"]}:
            enabled=st.checkbox("가상 트램 출발 목표 시각 입력",key="ua_tram_enabled")
            if enabled:
                default=request_time+timedelta(minutes=30)
                target_day=st.date_input("가상 트램 출발 날짜",default.date(),key="ua_tram_day")
                target_clock=st.time_input("가상 트램 출발시간",default.time().replace(tzinfo=None),key="ua_tram_time")
                tram_departure=datetime.combine(target_day,target_clock,KST)
                streamlit.caption("사용자가 정한 가상 시각이며 실제 시간표가 아닙니다.")
        inputs=[route_id,origin,destination,request_time.isoformat(),int(passengers),tram_departure.isoformat() if tram_departure else None,run_id]
        fingerprint=signature(inputs)
        tokens=streamlit.session_state.setdefault("ua_request_tokens",{})
        token=tokens.setdefault(fingerprint,'ui:'+fingerprint)
        if streamlit.button("예약 신청",key="ua_submit",type="primary"):
            try:
                record=service.create(origin,destination,request_time,int(passengers),token,allow_network=online,tram_departure=tram_departure,route_id=route_id,run_id=run_id)
                streamlit.session_state["ua_last_result"]=record
                from modules.reservation_audit import audit_records
                audited=audit_records([record],service.routes.original_loader(),service.routes.snapshot())[0]
                streamlit.success(f"{audited['display_stage']} · 저장 완료")
                streamlit.info(audited['review_reason'])
            except (RouteError,OSError,sqlite3.Error,ValueError) as error:
                streamlit.error(str(error))
        last=streamlit.session_state.get("ua_last_result")
        if last:
            with streamlit.expander("최근 접수 결과 및 배차 판정"):
                streamlit.write({k:last.get(k) for k in ("public_id","status","route_id","vehicle_id","dispatch_status","requested_at")})
        streamlit.caption("동일 조건 재신청은 중복 저장하지 않습니다.")
        with streamlit.expander('동일 조건으로 별도 추가 신청'):
            if streamlit.button("새 요청 준비",key="ua_new_request"):
                tokens[fingerprint]=uuid4().hex
                streamlit.info("새 요청이 준비됐습니다. 예약 신청을 눌러 접수하세요.")
    except (RouteError,OSError,sqlite3.Error,ValueError,KeyError) as error:
        streamlit.error(f"정류장 또는 예약 입력을 확인하세요: {error}")

def show_reservation_list():
    from modules.reservation_list_ui import show_booking_list
    show_booking_list(UnifiedReservations())


def show_simulation_compatibility():
    streamlit.subheader("통합 예약의 시뮬레이션 적용 범위")
    try:
        records=UnifiedReservations().list_records()
        active=[r for r in records if r["status"] in ACTIVE]
        excluded=[r for r in active if r["simulation_adapter"]=="excluded"]
        if excluded:
            streamlit.info(f"자동 시뮬레이션 제외 {len(excluded)}건: 배차 검토 또는 현재 엔진 미지원")
            streamlit.dataframe(pd.DataFrame([{"예약 ID":r["public_id"],"제외 사유":r["dispatch_status"]} for r in excluded]),hide_index=True)
        supported=[r for r in active if r["simulation_adapter"]=="r02"]
        if supported:
            selected=st.selectbox("독립 운행편 예정 일정 조회",[r["public_id"] for r in supported],key="ua_sim_booking")
            record=next(r for r in supported if r["public_id"]==selected)
            booking=record["booking_snapshot"]
            plan=booking_schedule(booking,booking.get("dwell_assumption_min",1))
            streamlit.caption("R02 저장 구간 기반 독립 연구용 예정 일정 · 기존 합승 엔진과 별도")
            streamlit.dataframe(pd.DataFrame(plan["rows"]),hide_index=True)
        streamlit.caption("아래 기존 합승 계산은 호환되는 기존 CSV 예약만 사용하며 취소 기록을 반영합니다. 날짜 기반 신규 요청을 날짜 없는 기존 그룹에 섞지 않습니다.")
    except (RouteError,OSError,sqlite3.Error,ValueError) as error:
        streamlit.error(f"적용 가능 예약 확인 실패: {error}")


def show_unified_reservations():
    show_booking_form()
    show_reservation_list()

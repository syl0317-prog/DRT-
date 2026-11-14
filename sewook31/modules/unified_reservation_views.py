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


def show_unified_reservations():
    streamlit.header("위례 DRT 통합 예약")
    streamlit.caption("노선과 정류장을 선택하세요. 배차 조건 미충족 시 배차 검토 필요로 접수합니다.")
    service=UnifiedReservations()
    try:
        catalog=service.catalog()
        streamlit.caption(f"저장된 DRT 정류장 {len(catalog['boarding'])}개 · 트램 거점 {len(catalog['trams'])}개")
        route_id=st.selectbox("이용 노선",["R01","R02"],key="ua_route")
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
        with right:
            include_tram=st.checkbox("트램 환승 거점도 하차 목록에 표시",key="ua_include_tram")
            destinations=ids+([s["stop_id"] for s in catalog["trams"]] if include_tram else [])
            destination=st.selectbox("하차 정류장",destinations,index=1,format_func=label,key="ua_destination")
        streamlit.caption("R01: D01~D04 및 트램 거점. R02: 저장된 V05~V08 방문 순서 및 연결된 거점. 다른 노선 조합은 저장 시 거절합니다.")
        future=datetime.now(KST)+timedelta(hours=1)
        left,right=streamlit.columns(2)
        with left:
            day=st.date_input("탑승 희망 날짜",future.date(),key="ua_day")
        with right:
            clock=st.time_input("탑승 희망 시간 (한국시간)",future.time().replace(second=0,microsecond=0,tzinfo=None),key="ua_time")
        passengers=st.number_input("탑승 인원",1,100,1,key="ua_passengers")
        online=st.checkbox("필요할 때 OSRM 온라인 경로 확인 허용",value=False,key="ua_online")
        streamlit.caption("경로 미확인·노선 간 이동·미지원 배차는 검토 상태입니다. 연구용 예정 운행편 배정은 실제 운행 확정이 아닙니다.")
        request_time=datetime.combine(day,clock,KST)
        tram_departure=None
        if destination in {s["stop_id"] for s in catalog["trams"]}:
            enabled=st.checkbox("가상 트램 출발 목표 시각 입력",key="ua_tram_enabled")
            if enabled:
                default=request_time+timedelta(minutes=30)
                target_day=st.date_input("가상 트램 출발 날짜",default.date(),key="ua_tram_day")
                target_clock=st.time_input("가상 트램 출발시간",default.time().replace(tzinfo=None),key="ua_tram_time")
                tram_departure=datetime.combine(target_day,target_clock,KST)
                streamlit.caption("사용자가 정한 가상 시각이며 실제 시간표가 아닙니다.")
        inputs=[route_id,origin,destination,request_time.isoformat(),int(passengers),tram_departure.isoformat() if tram_departure else None]
        fingerprint=signature(inputs)
        tokens=streamlit.session_state.setdefault("ua_request_tokens",{})
        token=tokens.setdefault(fingerprint,uuid4().hex)
        if streamlit.button("예약 신청",key="ua_submit",type="primary"):
            try:
                record=service.create(origin,destination,request_time,int(passengers),token,allow_network=online,tram_departure=tram_departure,route_id=route_id)
                streamlit.session_state["ua_last_result"]=record
                streamlit.success(f"{record['status']} · {record['public_id']}")
            except (RouteError,OSError,sqlite3.Error,ValueError) as error:
                streamlit.error(str(error))
        last=streamlit.session_state.get("ua_last_result")
        if last:
            with streamlit.expander("최근 접수 결과 및 배차 판정"):
                streamlit.write({k:last.get(k) for k in ("public_id","status","route_id","vehicle_id","dispatch_status","requested_at")})
        streamlit.caption("동일 입력을 다시 누르면 같은 요청으로 처리해 중복 저장하지 않습니다.")
        if streamlit.button("동일 조건으로 별도 추가 요청 준비",key="ua_new_request"):
            tokens[fingerprint]=uuid4().hex
            streamlit.info("새 요청 키가 준비됐습니다. 예약 신청을 눌러 별도로 접수하세요.")
    except (RouteError,OSError,sqlite3.Error,ValueError,KeyError) as error:
        streamlit.error(f"정류장 또는 예약 입력을 확인하세요: {error}")

    streamlit.divider()
    streamlit.subheader("통합 예약 현황")
    try:
        records=service.list_records()
        names={s["stop_id"]:s["name"] for s in service.catalog()["boarding"]+service.catalog()["trams"]}
        options=["전체","예약완료","배차 검토 필요","예약취소"]
        selected=st.selectbox("예약 상태 필터",options,key="ua_filter")
        selected_route=st.selectbox("예약 노선 필터",["전체","R01","R02"],key="ua_route_filter")
        rows=[]
        filtered_records=[]
        for record in records:
            if selected_route!="전체" and record["route_id"]!=selected_route:
                continue
            if selected!="전체" and record["status"]!=selected:
                continue
            filtered_records.append(record)
            instant=datetime.fromisoformat(record["requested_at"]).astimezone(KST) if record["requested_at"] else None
            rows.append({"예약 ID":record["public_id"],"탑승 정류장":names.get(record["boarding_stop"],record["boarding_stop"]),
                "하차 정류장":names.get(record["destination_stop"],record["destination_stop"]),
                "탑승 날짜":instant.date().isoformat() if instant else "미기록",
                "탑승 시간":instant.strftime("%H:%M") if instant else "미기록",
                "시간 의미":record["time_basis"],"탑승 인원":record["passengers"],"예약 상태":record["status"],
                "운행 경로":record["route_id"],"차량":record.get("vehicle_id") or "미배정",
                "배차 판정":record["dispatch_status"],"기존 가상 트램 시각":record.get("tram_departure") or "해당 없음"})
        streamlit.dataframe(pd.DataFrame(rows),hide_index=True)
        streamlit.caption("과거 CSV에 없는 탑승 날짜·희망 시간은 미기록으로 표시합니다. CSV 취소는 원본 보존용 취소 기록에 저장하며 기존 좌석 계산에도 반영합니다.")
        active=[r for r in filtered_records if r["status"] in ACTIVE]
        if active:
            public_id=st.selectbox("취소할 예약",[r["public_id"] for r in active],key="ua_cancel_id")
            if streamlit.button("선택 예약 취소",key="ua_cancel"):
                service.cancel(public_id)
                streamlit.session_state.pop("ua_last_result",None)
                streamlit.rerun()
    except (RouteError,OSError,sqlite3.Error,ValueError,KeyError) as error:
        streamlit.error(f"통합 조회/취소 실패: {error}")


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

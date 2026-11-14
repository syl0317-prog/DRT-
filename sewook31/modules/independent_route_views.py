"""Research route UI; separate data and click keys from the legacy route screen."""
from datetime import datetime, time
import html
import sqlite3
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import streamlit as streamlit
from streamlit_folium import st_folium

from modules.session_ui import persistent_ui as st, signature
from modules.map_background import background_map
from modules.independent_routes import RouteStore, RouteError, inspect_location, read_original_stops, booking_schedule

KST = ZoneInfo("Asia/Seoul")


def display_table(rows, drop=()):
    if rows:
        frame = pd.DataFrame(rows).drop(columns=list(drop), errors="ignore")
        streamlit.dataframe(frame.astype(str), hide_index=True)
    else:
        streamlit.info("등록된 데이터가 없습니다.")


def overlay_routes(map_object, state, show_original=True, legacy_preview=None):
    if show_original:
        for stop in read_original_stops():
            folium.CircleMarker([float(stop["latitude"]), float(stop["longitude"])], radius=6,
                color="#e17a18" if stop["stop_type"]=="tram" else "#2474d2", fill=True,
                tooltip=html.escape(f"{stop['stop_name']} ({stop['stop_id']})")).add_to(map_object)
    for stop in state["stops"]:
        popup = "<br>".join(html.escape(str(v)) for v in [stop["name"], stop["stop_id"],
                    "노선: "+stop["route_id"], "방문 순서: "+str(stop["position"]), "연구용 가상정류장"])
        folium.CircleMarker([stop["latitude"], stop["longitude"]], radius=9, color="#15803d",
                            fill=True, fill_opacity=.8, popup=popup, tooltip=html.escape(stop["name"])).add_to(map_object)
    for segment in state["segments"]:
        folium.PolyLine(segment["coordinates"], color="#15803d", weight=5,
                        tooltip=html.escape(f"{segment['route_id']} · OSRM 모형 · 사용자 지정 방문 순서")).add_to(map_object)
    if legacy_preview:
        folium.PolyLine(legacy_preview["route"]["coordinates"], color="#2474d2", weight=4,
                        tooltip="기존 화면의 현재 세션 임시 경로 · 저장 노선 아님").add_to(map_object)


def _change(operation):
    try:
        operation()
        streamlit.session_state.pop("nr_registry_revision",None)
        streamlit.success("별도 신규 노선 등록부에 저장했습니다.")
        streamlit.rerun()
    except (RouteError, OSError, sqlite3.Error, ValueError) as error:
        streamlit.error(f"저장/처리 실패: {error}")


def _revision_gate(state):
    """Keep the version the form was opened with, including across widget reruns."""
    key="nr_registry_revision"
    if key not in streamlit.session_state:
        streamlit.session_state[key]=state["revision"]
    if streamlit.session_state[key]==state["revision"]:
        return True
    streamlit.warning("다른 사용자 또는 화면에서 등록부를 변경했습니다. 입력을 초기화하고 현재 데이터를 다시 확인하세요.")
    if streamlit.button("신규 등록부 다시 불러오기 (입력 초기화)",key="nr_reload"):
        for value in list(streamlit.session_state):
            if value.startswith("nr_"):
                streamlit.session_state.pop(value,None)
        saved=streamlit.session_state.get("ui_saved_values",{})
        for value in list(saved):
            if value.startswith("nr_"):
                saved.pop(value,None)
        streamlit.rerun()
    return False


def show_route_management():
    streamlit.header("신규 독립 노선 관리")
    streamlit.caption("R01은 기존 CSV 경유지 기능의 화면 식별자이며, R02는 SQLite에 저장하는 독립 노선입니다.")
    store = RouteStore()
    try:
        state = store.snapshot()
    except (OSError, sqlite3.Error, RouteError) as error:
        streamlit.error(f"노선 등록부 읽기 실패: {error}")
        return
    if not _revision_gate(state):
        return
    if not state["routes"]:
        streamlit.info("신규 노선 등록 대기입니다. 위치가 없는 초안만 먼저 생성할 수 있습니다.")
        route_id = st.text_input("신규 노선 ID", "R02", key="nr_route_id")
        name = st.text_input("신규 노선명", "위례 DRT 신규 노선", key="nr_name")
        if streamlit.button("신규 노선 초안 생성", key="nr_create"):
            _change(lambda:store.create_route(route_id, name, state["revision"]))
        return
    route = state["routes"][0]
    rid = route["route_id"]
    streamlit.subheader(f"{rid} · {route['name']}")
    streamlit.caption(f"연구용 가상 DRT · 독립 노선 · {'활성' if route['active'] else '등록/계산 대기'} · 등록부 버전 {state['revision']}")
    choice = st.radio("노선 보기", [f"신규 노선 {rid}", "전체 정류장·저장 노선", "기존 경유지 계산"],
                      horizontal=True, key="nr_map_choice")
    if choice == "기존 경유지 계산":
        from modules.route_views import show_drt_map
        show_drt_map()
        return
    map_object = background_map([37.474, 127.143], zoom_start=14)
    overlay_routes(map_object, state, show_original=True,
                   legacy_preview=streamlit.session_state.get("legacy_map_preview") if choice=="전체 정류장·저장 노선" else None)
    points = [[s["latitude"], s["longitude"]] for s in state["stops"]]
    if points:
        original_points = [[float(s["latitude"]),float(s["longitude"])] for s in read_original_stops()]
        map_object.fit_bounds(points+original_points, padding=(25,25), max_zoom=16)
    clicked = st_folium(map_object, height=440, key="new_route_registration_map", returned_objects=["last_clicked"])
    if clicked and clicked.get("last_clicked"):
        point = clicked["last_clicked"]
        streamlit.session_state["new_route_clicked"] = dict(latitude=point["lat"], longitude=point["lng"])
    streamlit.caption("초록: 신규 후보·저장 OSRM 경로 / 파랑: 기존 정류장·현재 세션 임시 경로 / 주황: 기존 트램 거점. 지도 선택은 저장이 아닙니다.")
    streamlit.info("분석 범위는 V-World 도로망의 외접 범위입니다. 행정경계가 아니며 도로와 가깝더라도 승하차 안전성·통행 가능·정차 허용을 의미하지 않습니다.")

    streamlit.subheader("가상정류장 등록·수정 (정확히 4개)")
    stops = sorted(state["stops"], key=lambda s:s["position"])
    display_table(stops, drop=("roads_sha256",))
    options = ["새 정류장"]+[s["stop_id"] for s in stops]
    edit = st.selectbox("등록 또는 수정 대상", options, key="nr_edit")
    existing = next((s for s in stops if s["stop_id"]==edit), None)
    suffix = edit if existing else "new_"+store.suggested_stop_ids()[0]
    source = st.radio("좌표 입력 방식", ["위도·경도 입력", "지도에서 선택한 위치"], key="nr_coord_source")
    selected = streamlit.session_state.get("new_route_clicked")
    sid = st.text_input("가상정류장 ID", existing["stop_id"] if existing else store.suggested_stop_ids()[0],
                       disabled=existing is not None, key="nr_stop_id_"+suffix)
    streamlit.caption("현재 사용 가능한 ID 제안: "+", ".join(store.suggested_stop_ids()))
    name = st.text_input("가상정류장 이름", existing["name"] if existing else "", key="nr_stop_name_"+suffix)
    if source == "지도에서 선택한 위치":
        lat, lon = (selected["latitude"],selected["longitude"]) if selected else (None,None)
        streamlit.write(f"선택 좌표: {lat}, {lon}")
    else:
        lat = st.number_input("신규 위도", value=existing["latitude"] if existing else None, format="%.8f", key="nr_lat_"+suffix)
        lon = st.number_input("신규 경도", value=existing["longitude"] if existing else None, format="%.8f", key="nr_lon_"+suffix)
    free = next((i for i in range(1,5) if i not in {s["position"] for s in stops}), 1)
    position = st.number_input("신규 정류장 방문 순서", 1, 4, existing["position"] if existing else free, key="nr_position_"+suffix)
    status = st.selectbox("신규 정류장 등록 상태", ["연구용 후보", "검토 완료"],
                         index=1 if existing and existing["registration_status"]=="reviewed" else 0, key="nr_status_"+suffix)
    streamlit.caption("검토 완료 표기는 사용자 검토 기록입니다. 실제 운행·정차 허가나 안전 인증이 아닙니다.")
    if streamlit.button("입력 좌표·도로 접근 거리 검토",key="nr_check_position"):
        try:
            checked=inspect_location(lat,lon,read_original_stops()+[s for s in stops if not existing or s["stop_id"]!=existing["stop_id"]])
            streamlit.json(checked)
        except (RouteError,OSError,ValueError) as error:
            streamlit.error(str(error))
    confirmed = st.checkbox("정류장 이름·좌표·순서를 확인했으며 연구용 후보로 등록합니다",
                            key="nr_confirm_"+signature([sid,name,lat,lon,position,status])[:12])
    if streamlit.button("정류장 저장", key="nr_save_stop"):
        if not confirmed:
            streamlit.error("저장 전에 이름과 좌표를 확인하세요.")
        else:
            _change(lambda:store.put_stop(rid,sid,name,lat,lon,int(position),
                "reviewed" if status=="검토 완료" else "research_candidate",state["revision"],replace_id=existing["stop_id"] if existing else None))

    streamlit.subheader("방문 순서·환승 거점·별도 차량 설정")
    if len(stops)==4:
        order, remaining = [], [s["stop_id"] for s in stops]
        for i in range(4):
            key = st.selectbox(f"신규 노선 {i+1}번째 정류장", remaining, key=f"nr_order_{i}")
            order.append(key); remaining = [r for r in remaining if r!=key]
        trams = [s for s in read_original_stops() if s["stop_type"]=="tram"]
        tram_options = ["연결 안 함"]+[s["stop_id"] for s in trams]
        transfer = st.selectbox("신규 노선 종점 트램 거점", tram_options,
                                index=tram_options.index(route["transfer_stop_id"]) if route["transfer_stop_id"] else 0,key="nr_tram")
        vehicles = st.text_input("신규 전용 연구용 차량 ID (쉼표 구분)",
            ",".join(v["vehicle_id"] for v in route["vehicles"]) or rid+"-V01", key="nr_vehicles")
        capacity = st.number_input("신규 연구용 차량별 정원",1,100,route["vehicles"][0]["capacity"] if route["vehicles"] else 8,key="nr_capacity")
        if streamlit.button("방문 순서·차량 설정 저장",key="nr_configure"):
            fleet=[dict(vehicle_id=v.strip(),capacity=int(capacity)) for v in vehicles.split(",") if v.strip()]
            _change(lambda:store.configure(rid,order,None if transfer=="연결 안 함" else transfer,fleet,state["revision"]))
    else:
        streamlit.info(f"등록 {len(stops)}/4개. 임의 좌표는 채우지 않습니다.")
    allow_network = st.checkbox("신규 노선 OSRM 온라인 조회 허용 (기존 캐시는 읽기 전용)",key="nr_online")
    if streamlit.button("신규 노선 OSRM 구간 경로 계산",key="nr_calculate"):
        _change(lambda:store.calculate(rid,state["revision"],allow_network=allow_network))
    streamlit.write(f"경로 상태: {route['calculation_status']} / 거리: {route['distance_km'] if route['distance_km'] is not None else '미계산'} km / 이동시간: {route['duration_min'] if route['duration_min'] is not None else '미계산'} 분")
    if route.get("error"):
        streamlit.error(route["error"]+" · 직선을 운행경로로 대체하지 않았습니다.")
    display_table(state["segments"],drop=("coordinates",))
    if streamlit.button("신규 연구용 노선 활성화" if not route["active"] else "신규 노선 비활성화",key="nr_activate"):
        _change(lambda:store.set_active(rid,not route["active"],state["revision"]))
    if streamlit.button("신규 노선 JSON·CSV 스냅샷 내보내기",key="nr_export"):
        try:
            streamlit.success(str(store.export()))
        except (OSError,ValueError,sqlite3.Error) as error:
            streamlit.error(f"별도 내보내기 실패: {error}")


def show_new_route_reservations():
    streamlit.header("신규 독립 노선 예약 · 연구용")
    streamlit.caption("기존 예약 CSV 및 배차 엔진과 분리된 예약입니다. 기존 예약은 노선 미지정 상태 그대로 유지합니다.")
    store = RouteStore()
    try:
        state = store.snapshot()
    except (OSError,sqlite3.Error,RouteError) as error:
        streamlit.error(f"신규 등록부 읽기 실패: {error}")
        return
    if not _revision_gate(state):
        return
    choices = [r for r in state["routes"] if r["active"]]
    if not choices:
        streamlit.info("예약 가능한 신규 활성 노선이 없습니다. 배차·경로 → 신규 독립 노선에서 4개 정류장과 경로를 등록하세요.")
    else:
        rid = st.selectbox("예약할 신규 노선",[r["route_id"] for r in choices],key="nr_booking_route")
        route=next(r for r in choices if r["route_id"]==rid)
        order=route["stop_order"]+([route["transfer_stop_id"]] if route["transfer_stop_id"] else [])
        name_lookup={s["stop_id"]:s["name"] for s in state["stops"]}
        name_lookup.update({s["stop_id"]:s["stop_name"] for s in read_original_stops()})
        label=lambda key:f"{name_lookup[key]} ({key})"
        boarding=st.selectbox("신규 노선 탑승 정류장",order[:-1],format_func=label,key="nr_boarding")
        destination=st.selectbox("신규 노선 도착 정류장",order[order.index(boarding)+1:],format_func=label,key="nr_destination")
        vehicle=st.selectbox("신규 노선 별도 차량",[v["vehicle_id"] for v in route["vehicles"]],key="nr_booking_vehicle")
        day=st.date_input("신규 노선 운행 날짜",datetime.now(KST).date(),key="nr_service_date")
        clock=st.time_input("신규 노선 첫 정류장 출발시각",time(8),key="nr_service_time")
        passengers=st.number_input("신규 예약 승객 수",1,100,1,key="nr_passengers")
        dwell=st.number_input("신규 운행편 정차 가정 (분)",0.,30.,1.,key="nr_booking_dwell")
        streamlit.caption("운행편별 정원을 전 구간에 보수적으로 적용합니다. 실제 차량 운용 가능·운행허가는 별도 확인해야 합니다.")
        if streamlit.button("신규 노선 예약 생성",key="nr_book"):
            _change(lambda:store.reserve(rid,boarding,destination,vehicle,datetime.combine(day,clock,KST),int(passengers),state["revision"],dwell_min=dwell))
    streamlit.subheader("신규 노선 예약 내역")
    display_table(state["bookings"],drop=("route_snapshot","segments_snapshot"))
    active=[b for b in state["bookings"] if b["status"]=="reserved"]
    if active:
        bid=st.selectbox("조회·취소할 신규 예약",[b["reservation_id"] for b in active],key="nr_booking_id")
        booking=next(b for b in active if b["reservation_id"]==bid)
        buffer=st.number_input("신규 일정 환승 여유 가정 (분)",0.,60.,5.,key="nr_transfer_buffer")
        schedule=booking_schedule(booking,booking["dwell_assumption_min"],buffer)
        streamlit.caption("독립적인 예정 일정 · 기존 역산 배차/최적화 알고리즘과 별개 · 저장 OSRM 구간 + 입력 가정")
        display_table(schedule["rows"])
        streamlit.write("예약 탑승 정류장 예정시각: "+schedule["boarding_at"])
        streamlit.write("예약 목적지 도착 가정 시각: "+schedule["destination_arrival"])
        streamlit.write("예약 목적지 추가 여유 반영시각: "+schedule["ready_at"])
        if streamlit.button("신규 노선 예약 취소",key="nr_cancel"):
            _change(lambda:store.cancel(bid,state["revision"]))


def show_route_summary(state, legacy_reservations=None, unified_records=None):
    streamlit.subheader("노선 현황 · 별도 연구용 등록부")
    streamlit.caption("기존 경유지 계산은 저장 노선 수에 포함하지 않습니다. 기존 예약은 신규 노선에 자동 배정하지 않습니다.")
    streamlit.write(f"등록된 신규 노선 수: {len(state['routes'])}")
    original=read_original_stops()
    if legacy_reservations is not None:
        count=int(legacy_reservations.status.eq("예약완료").sum())
        streamlit.caption(f"기존 방식 (노선 미지정): DRT 정류장 {sum(s['stop_type']=='drt' for s in original)}개 · 환승 거점 {sum(s['stop_type']=='tram' for s in original)}개 · 유효 예약 {count}건. 저장 노선 수에는 포함하지 않습니다.")
    rows=[]
    for route in state["routes"]:
        own=[s for s in state["stops"] if s["route_id"]==route["route_id"]]
        bookings=([b for b in unified_records if b["route_id"]==route["route_id"] and b["status"] in ("예약완료","배차 검토 필요")]
                  if unified_records is not None else [b for b in state["bookings"] if b["route_id"]==route["route_id"] and b["status"]=="reserved"])
        rows.append({"노선":route["route_id"],"상태":"연구용 활성" if route["active"] else "등록/계산 대기",
            "신규 정류장":len(own),"신규 유효 예약":len(bookings),"신규 승객":sum(b["passengers"] for b in bookings),
            "예상 거리(km)":route["distance_km"] if route["distance_km"] is not None else "미계산",
            "예상 이동시간(분)":route["duration_min"] if route["duration_min"] is not None else "미계산"})
    display_table(rows)

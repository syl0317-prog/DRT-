"""Peak fixed-route timetable, reliability evidence and demand-based fleet sizing."""
from datetime import datetime, timedelta

import pandas as pd
import streamlit as streamlit

from modules.session_ui import persistent_ui as st
from modules.peak_operations import KST, PERIODS, demand, next_weekdays, timetable


def _window(w):
    return w["start"].strftime("%H:%M") + ("" if w["start"] == w["end"] else "~" + w["end"].strftime("%H:%M"))


def trips_frame(table):
    rows = []
    for trip in table["trips"]:
        row = {"편": trip["trip"], "트램 출발": trip["tram_departure"].strftime("%H:%M"),
               "DRT 첫 정류장 출발": trip["departure"].strftime("%H:%M")}
        for w in trip["windows"]:
            row[f"{w['stop_name']} 승차"] = _window(w)
        row["환승역 도착 범위"] = f"{trip['arrival_start']:%H:%M}~{trip['arrival_end']:%H:%M}"
        row["환승 성공률(%)"] = round(trip["success_pct"], 1)
        row["평균 트램 대기(분)"] = round(trip["mean_tram_wait"], 1)
        rows.append(row)
    return pd.DataFrame(rows)


def show_peak_operations():
    streamlit.subheader("출퇴근 고정노선 시간표 · 운영 조정")
    streamlit.caption("트램 출발시각에서 역산한 DRT 시간표입니다. 혼잡을 반영한 통행시간 분포의 상위 분위수로 출발시각을 정해 "
                      "환승 성공 목표를 맞춥니다. 가상 트램 시간표·도로 모형 기반 연구 결과이며 실제 운행 실적이 아닙니다.")
    from modules.punctuality_routes import route_legs
    legs, problems = route_legs()
    routes = sorted({leg["route_id"] for leg in legs if leg["road_min"] is not None})
    if not routes:
        streamlit.error("도로 모형이 확인된 노선이 없습니다. " + " / ".join(problems))
        return
    cols = st.columns(5)
    with cols[0]:
        route_id = st.selectbox("노선", routes, key="peak_route")
    with cols[1]:
        default_day = next_weekdays(datetime.now(KST).date() + timedelta(days=1), 1)[0]
        day = st.date_input("운행일 (평일)", default_day, key="peak_day")
    with cols[2]:
        period = st.selectbox("시간대", list(PERIODS), key="peak_period")
    with cols[3]:
        walk = st.number_input("환승 보행시간(분)", 0.0, 15.0, 3.0, .5, key="peak_walk")
    with cols[4]:
        reliability = st.slider("환승 성공 목표(%)", 50, 99, 95, key="peak_reliability") / 100
    try:
        table = timetable(route_id, day, period, walk, reliability, legs=legs)
    except (ValueError, OSError, KeyError) as error:
        streamlit.error(str(error))
        return
    model = table["model"]
    if route_id in ("R03", "R04"):
        streamlit.warning("R03·R04는 차량 접근·정차·회차 검증 전입니다. 시간표는 도로 모형 기준 계획안이며 배차 확정은 불가합니다.")

    streamlit.markdown(f"**{route_id} → {table['station']} · {period} · 통행시간 신뢰도**")
    metrics = streamlit.columns(5)
    metrics[0].metric("비혼잡 통행시간", f"{model['free_flow']:.1f}분")
    metrics[1].metric("중앙값", f"{model['q50']:.1f}분")
    metrics[2].metric("95% 통행시간", f"{model['q95']:.1f}분")
    metrics[3].metric("버퍼 지수", f"{model['buffer_index']:.2f}", help="(95% 통행시간 − 평균) ÷ 평균. 클수록 혼잡 변동이 커서 여유시간이 더 필요합니다.")
    metrics[4].metric("계획시간 지수", f"{model['planning_time_index']:.2f}", help="95% 통행시간 ÷ 비혼잡 통행시간")
    streamlit.caption(f"혼잡계수 k 최소/최빈/최대 = {model['k'][0]:.2f} / {model['k'][1]:.2f} / {model['k'][2]:.2f} · {model['basis']} · "
                      f"차내시간은 중간 정차 포함 · 시뮬레이션 {len(model['total']):,}회")

    streamlit.markdown("**역산 시간표 · 정류장별 승차 타임윈도우**")
    streamlit.caption("정류장 이름은 검토용 명칭 후보입니다(현장 미검증).")
    streamlit.dataframe(trips_frame(table), hide_index=True)
    streamlit.caption(f"DRT 출발 = 트램 출발 − 보행 {walk:g}분 − 통행시간 {reliability:.0%} 분위수 (분 단위 내림). "
                      "승차 타임윈도우 = 차량이 정류장에 도착할 수 있는 5~95% 범위이며, 이용객은 시작 시각까지 정류장에 나와야 합니다. "
                      f"트램 시각: 첫차 06:00 마천역 출발·피크 배차 가정 · {table['station']}역 도착 오프셋은 tram_timetable.json 구간 시간 합계입니다.")

    streamlit.markdown("**시간대별 예약 수요 · 차량 수/배차간격/예약률 조정**")
    try:
        from modules.unified_reservations import UnifiedReservations
        records = UnifiedReservations().list_records()
    except Exception as error:  # Booking store problems must not hide the timetable.
        streamlit.warning(f"예약 기록을 읽지 못했습니다: {error}")
        records = []
    result = demand(table, records)
    frame = pd.DataFrame([{"편": r["trip"], "트램 출발": r["tram_departure"].strftime("%H:%M"), "예약 인원": r["passengers"],
                           "필요 차량(대)": r["vehicles"], "예약률(%)": round(r["load_pct"], 1)} for r in result["rows"]])
    streamlit.dataframe(frame, hide_index=True)
    cols = streamlit.columns(4)
    cols[0].metric("해당 시간대 예약", f"{result['total']}명")
    cols[1].metric("권장 DRT 배차간격", f"{result['drt_headway']:g}분")
    cols[2].metric("권장 차량 수", f"{result['vehicles']}대")
    cols[3].metric("현재 연구용 차량 수", f"{int(streamlit.session_state.get('vehicle_count', 4))}대")
    streamlit.caption(f"{result['note'] if result['total'] else '예약 없음 · 최소 운행 기준(트램 2편마다 1회)'} · 차량 정원 {result['capacity']}명 · "
                      f"1회 순환 {result['cycle']:.1f}분 = 95% 통행시간 + 회차(같은 도로 모형·최빈 혼잡 가정) + 대기 2분.")

    with streamlit.expander(f"{period} 전체 노선 비교"):
        summary = []
        for rid in routes:
            try:
                other = timetable(rid, day, period, walk, reliability, legs=legs)
            except ValueError:
                continue
            m = other["model"]
            summary.append({"노선": rid, "환승역": other["station"], "비혼잡(분)": round(m["free_flow"], 1),
                            "중앙값(분)": round(m["q50"], 1), "95%(분)": round(m["q95"], 1),
                            "버퍼 지수": round(m["buffer_index"], 2),
                            "평균 트램 대기(분)": round(sum(t["mean_tram_wait"] for t in other["trips"]) / len(other["trips"]), 1),
                            "혼잡 근거": m["basis"]})
        streamlit.dataframe(pd.DataFrame(summary), hide_index=True)
        streamlit.caption("버퍼 지수가 큰 노선일수록 환승 성공을 위해 일찍 출발해야 하고, 그만큼 트램 대기가 늘어납니다. "
                          "가정값 도로 비율이 큰 노선은 현장 실측 후 수치가 바뀔 수 있습니다('혼잡 근거·실측 입력' 탭).")
    if problems:
        with streamlit.expander("시간표에서 제외된 정류장"):
            for problem in problems:
                streamlit.write("· " + problem)

"""Congestion evidence per route and field travel-time entry."""
from datetime import datetime, time, timedelta

import pandas as pd
import streamlit as streamlit

from modules.session_ui import persistent_ui as st
from modules import congestion_basis as cb
from modules.peak_operations import KST, PERIODS


def show_congestion_evidence():
    streamlit.subheader("혼잡 근거 · 현장 실측 입력")
    streamlit.caption("노선이 실제로 지나는 도로를 국가표준 노드링크(MOCT_LINK)와 매칭해, 도로마다 어떤 혼잡 자료를 쓰는지 보여줍니다. "
                      f"같은 노선·시간대 실측이 {cb.MIN_OBSERVED}건 이상 쌓이면 시간표·정시성 계산이 실측 비율로 바뀝니다.")
    from modules.punctuality_routes import route_legs
    legs, _problems = route_legs()
    routes = sorted({leg["route_id"] for leg in legs if leg["road_min"] is not None})
    if not routes:
        streamlit.error("도로 모형이 확인된 노선이 없습니다.")
        return
    route_id = st.selectbox("노선", routes, key="cg_route")
    comp = cb.composition(route_id)

    streamlit.markdown("**1. 노선 도로 구성과 혼잡 자료 적용 기준**")
    if comp is None:
        streamlit.warning("도로 매칭 결과가 없습니다. scripts/match_route_links.py를 실행하세요(국가표준 노드링크 원본 필요).")
    else:
        cols = streamlit.columns(3)
        cols[0].metric("간선(국도·고속도로)", f"{comp['arterial']:.0%}", help="GITS 평일 시간대 속도 자료와 같은 등급의 도로")
        cols[1].metric("그 외 도로", f"{comp['local']:.0%}")
        cols[2].metric("링크 미매칭", f"{comp['unmatched']:.0%}", help="노드링크에 없는 단지 내 도로 등. 가정값 적용")
        streamlit.dataframe(pd.DataFrame([{"도로": r["road"], "도로 등급": r["rank"], "길이(m)": round(r["length_m"]),
                                           "비율(%)": round(r["share"] * 100, 1), "적용 혼잡 자료": r["source"]}
                                          for r in cb.road_table(route_id)]), hide_index=True)
    factors = []
    for period in PERIODS:
        factor = cb.route_factor(route_id, period)
        factors.append({"시간대": period, "혼잡계수 최소/최빈/최대": " / ".join(f"{v:.2f}" for v in factor["k"]),
                        "근거 유형": {"observed": "현장 실측", "composite": "도로 구성 가중", "assumption": "가정값"}[factor["kind"]],
                        "실측 건수": factor["n"], "근거": factor["basis"]})
    streamlit.dataframe(pd.DataFrame(factors), hide_index=True)
    streamlit.caption("기준: 국도·고속도로(MOCT 등급 101~103)는 GITS 측정 구간과 같은 등급이므로 그 시간대 속도비를 대리 적용하고, "
                      "시·군도와 단지 내 도로는 시간대 자료가 없어 가정값을 씁니다. 가정값 비중이 큰 노선일수록 실측이 우선입니다.")

    streamlit.markdown("**2. 현장 실측 입력**")
    own = sorted([leg for leg in legs if leg["route_id"] == route_id], key=lambda leg: leg["position"])
    by_id = {leg["stop_id"]: leg for leg in own}
    cols = st.columns(3)
    with cols[0]:
        day = st.date_input("측정일", datetime.now(KST).date(), key="cg_day")
        period = st.selectbox("시간대", list(PERIODS), key="cg_period")
    with cols[1]:
        origin = st.selectbox("출발 정류장", list(by_id), format_func=lambda k: f"{by_id[k]['position']}. {by_id[k]['stop_name']} ({k})", key="cg_origin")
        start = st.time_input("출발 시각", time(7, 30) if period == "출근" else time(17, 30), key="cg_start", step=60)
    with cols[2]:
        end = st.time_input(f"{by_id[origin]['destination_name']} 도착 시각", time(7, 40) if period == "출근" else time(17, 40), key="cg_end", step=60)
        seconds = st.number_input("도착 초(선택)", 0, 59, 0, key="cg_seconds")
    mode = st.radio("측정 방식", ["승용차·택시 주행 (중간 정차 없음)", "버스·DRT 탑승 (중간 정차 포함)"], horizontal=True, key="cg_mode")
    leg = by_id[origin]
    model = leg["road_min"] if mode.startswith("승용차") else leg["ride_min"]
    begin = datetime.combine(day, start)
    finish = datetime.combine(day, end) + timedelta(seconds=int(seconds))
    if finish <= begin:
        finish += timedelta(days=1)
    observed = (finish - begin).total_seconds() / 60
    streamlit.info(f"실측 {observed:.1f}분 · 모형 {model:.2f}분 (저장 OSRM 도로 모형{' + 중간 정차' if not mode.startswith('승용차') else ''}) · 비율 {observed / model:.2f}")
    if not PERIODS[period][0] <= start < PERIODS[period][1]:
        streamlit.warning(f"출발 시각이 {period} 시간대({PERIODS[period][0]:%H:%M}~{PERIODS[period][1]:%H:%M}) 밖입니다.")
    source = st.text_input("출처 (측정자 · 기록 방법, 예: 홍OO 휴대폰 타이머·GPS 로그)", "", key="cg_source")
    verified = st.checkbox("기록을 확인했습니다 (검증 완료로 계산에 반영)", value=False, key="cg_verified")
    memo = st.text_input("메모 (날씨, 사고, 신호 대기 등)", "", key="cg_memo")
    if streamlit.button("실측 저장", key="cg_save", type="primary"):
        try:
            cb.append_observation({"측정일": day.isoformat(), "출발지": origin, "도착지": leg["destination_id"],
                                   "실측소요분": round(observed, 3), "OSRM소요분": round(model, 3),
                                   "검증상태": "verified" if verified else "unverified", "출처": source.strip(),
                                   "노선": route_id, "시간대": period, "출발시각": start.strftime("%H:%M"),
                                   "측정방식": "주행" if mode.startswith("승용차") else "탑승", "메모": memo.strip()})
            streamlit.session_state["cg_saved_message"] = f"{route_id} {period} 실측 {observed:.1f}분 저장 · data/assumptions/travel_time_observed.csv를 커밋하면 팀원에게도 반영됩니다."
            streamlit.rerun()
        except (ValueError, OSError) as error:
            streamlit.error(str(error))

    message = streamlit.session_state.pop("cg_saved_message", None)
    if message:
        streamlit.success(message)
    streamlit.markdown("**3. 입력된 실측 기록**")
    rows = [r for r in cb.read_observations() if r.get("노선") == route_id]
    if rows:
        frame = pd.DataFrame(rows)
        streamlit.dataframe(frame[[c for c in cb.OBSERVED_FIELDS if c in frame]], hide_index=True)
    else:
        streamlit.info("아직 이 노선의 실측 기록이 없습니다.")
    progress = [{"노선": rid, "시간대": p, "검증 실측": len(cb.observed_ratios(rid, p)), "필요": cb.MIN_OBSERVED,
                 "가정값 도로 비율(%)": round((1 - (cb.composition(rid) or {"arterial": 0})["arterial"]) * 100)}
                for rid in routes for p in PERIODS]
    streamlit.dataframe(pd.DataFrame(progress).sort_values(["검증 실측", "가정값 도로 비율(%)"], ascending=[True, False]), hide_index=True)
    streamlit.caption("측정 우선순위: 검증 실측이 적고 가정값 도로 비율이 큰 노선·시간대부터 측정하세요. 노선 첫 정류장에서 환승역까지 측정하면 노선 전체가 보정됩니다.")

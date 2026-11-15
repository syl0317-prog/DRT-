"""Map-click editor reusing the existing st_folium last_clicked workflow."""
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
from modules.map_background import background_map
from modules.new_routes import boarding_stops, destination_stops, plans, show_validation
from modules.new_stop_settings import migrate_file, save_stop, clicked_point, query_road
from modules.session_ui import persistent_ui as ui
from modules.stop_labels import stop_label


def show_new_stop_settings():
    st.subheader('신규 정류장 위치 설정')
    st.caption('지도 클릭 → 후보 좌표 확인 → 저장. 지도 클릭만으로 도로 연결·정차 가능성이 검증되지는 않습니다.')
    try:
        data = migrate_file()
        rid = ui.selectbox('설정할 신규 노선', ['R03', 'R04'], key='ns_route')
        lookup = {s['stop_id']: s for s in boarding_stops() + destination_stops()}
        ids = [rid+'-S01', rid+'-S02', rid+'-BOKJEONG']
        sid = ui.selectbox('위치 설정 대상', ids,
            format_func=lambda k: stop_label(k,lookup[k]['name']),
            key='ns_stop_'+rid)
        token = f"{sid}:{data['revision']}"
        key = 'ns_click_'+token
        point = st.session_state.get(key)
        selected = lookup[sid]
        center = [selected['latitude'], selected['longitude']] if selected['latitude'] is not None else [37.474, 127.143]
        m = background_map(center, zoom_start=15)
        for stop in lookup.values():
            if stop['latitude'] is not None:
                folium.Marker([stop['latitude'], stop['longitude']],
                    tooltip=f"{stop_label(stop['stop_id'],stop['name'])} · {stop['coordinate_status']}").add_to(m)
        plan = next(p for p in plans() if p['route_id'] == rid)
        from modules.combined_routes import add_route_paths
        add_route_paths(m, plan)
        if point:
            folium.Marker([point['latitude'], point['longitude']], tooltip='저장 전 임시 후보',
                icon=folium.Icon(color='red')).add_to(m)
        event = st_folium(m, height=470, key='ns_map_'+token, returned_objects=['last_clicked'])
        clicked = clicked_point(event)
        if clicked and clicked != point:
            st.session_state[key] = clicked
            st.rerun()
        if point:
            st.write(f"선택 위도: {point['latitude']:.8f} · 경도: {point['longitude']:.8f}")
        else:
            st.info('지도에서 저장할 도로변 후보 위치를 클릭하세요.')
        if selected['latitude'] is not None:
            st.caption(f"현재 위치: {selected['latitude']:.8f}, {selected['longitude']:.8f} · {selected['coordinate_status']}")
        if sid.endswith('-BOKJEONG'):
            st.caption(f'{rid} 전용 복정역 하차 후보입니다. 다른 노선의 하차 위치는 변경되지 않습니다. 기존 공통 좌표는 초기 후보로만 사용합니다.')
        st.caption('좌표 수정 시 해당 노선의 저장 OSRM 경로만 해제됩니다. 다른 노선의 좌표·경로는 유지됩니다.')
        if st.button('후보 좌표 저장', key='ns_save', disabled=point is None):
            save_stop(sid, point['latitude'], point['longitude'], data['revision'])
            st.session_state['ns_notice'] = f'{stop_label(sid,selected["name"])} · 사용자 지정 후보 좌표 저장 완료'
            st.rerun()
        if st.session_state.get('ns_notice'):
            st.success(st.session_state.pop('ns_notice'))
        st.dataframe(pd.DataFrame([{'정류장': k, '이름': stop_label(k,lookup[k]['name']),
            '위도': lookup[k]['latitude'], '경도': lookup[k]['longitude'],
            '좌표 상태': lookup[k]['coordinate_status'], '차량 접근': lookup[k]['access_status']} for k in ids]), hide_index=True)
        st.subheader('순차 도로 경로 조회')
        st.caption('저장한 승차 후보 2개 → 복정역 하차 후보 순서로 OSRM driving 모형을 조회합니다. 클릭한 후보 좌표가 공개 OSRM 서비스로 전송됩니다. 실측·정차 허가·회차 검증 결과가 아닙니다.')
        if st.button('선택 노선 OSRM 도로 경로 조회', key='ns_query'):
            with st.spinner('순차 도로 모형 확인 중'):
                road = query_road(rid, data['revision'])
            st.session_state['ns_notice'] = f"OSRM 경로 저장 · {road['distance_km']:.2f} km · {road['duration_min']:.1f}분 · 차량 접근·정차 검증 필요"
            st.rerun()
        show_validation()
    except (OSError, ValueError, KeyError, TypeError) as error:
        st.error(f'좌표/경로 설정 실패: {error}')

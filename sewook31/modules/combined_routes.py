"""Common read-only operating map, using archived road geometry first."""
import html
import folium
from modules.independent_routes import RouteStore
from modules.route_engine import calculate_road_route
from modules.fixed_routes import COLORS, DESTINATIONS, resolve_stop


def route_layers(originals, state, order=None, destination=None, allow_network=False):
    from modules.sequential_routes import route_plans
    return route_plans(originals,state)


def add_layers(map_object, routes, visible):
    for route in routes:
        rid = route['route_id']; color = COLORS[rid]
        layer = folium.FeatureGroup(name=f'{rid} · 고정 목적지', show=rid in visible)
        for index,stop in enumerate(route['stops'],1):
            label = html.escape(f"{index}. {stop['name']} ({stop['stop_id']}) · {rid} · 최종 목적지 {DESTINATIONS[rid]}")
            point = [float(stop['latitude']), float(stop['longitude'])]
            if stop.get('stop_type') == 'tram':
                folium.Marker(point, tooltip=label, popup=label,
                    icon=folium.Icon(color='darkpurple', icon='train', prefix='fa')).add_to(layer)
            else:
                folium.Marker(point,tooltip=label,popup=label,icon=folium.DivIcon(
                    html=f'<div style="background:{color};color:white;border:2px solid white;border-radius:50%;width:25px;height:25px;text-align:center;font-weight:bold;line-height:23px">{index}</div>')).add_to(layer)
        for path in route['paths']:
            if len(path) >= 2:
                folium.PolyLine(path, color=color, weight=5,
                    tooltip=f'{rid} · OSRM 저장 도로 모형 · 실측 아님').add_to(layer)
        for path in route.get('estimated_paths', []):
            folium.PolyLine(path, color=color, weight=4, dash_array='8,8',
                tooltip=f'{rid} · 추정 연결선 · 실제 주행 경로 미확인').add_to(layer)
        for access in route.get('access',[]):
            if access['snap_m']>1:
                folium.PolyLine(access['coordinates'],color=color,weight=2,dash_array='3,6',opacity=.6,
                    tooltip=f"{access['stop_id']} · 정류장 접근 미검증 ({access['snap_m']:.1f}m)").add_to(layer)
        layer.add_to(map_object)


def show_combined_map(height=460,compact=False):
    import streamlit as streamlit
    from streamlit_folium import st_folium
    from modules.session_ui import persistent_ui as st
    from modules.map_background import background_map
    store = RouteStore()
    streamlit.subheader('R01·R02 통합 운행 지도')
    visible = st.multiselect('표시할 노선', list(DESTINATIONS), default=list(DESTINATIONS), key='combined_visible')
    routes = route_layers(store.original_loader(), store.snapshot())
    m = background_map([37.474, 127.143], zoom_start=14, layer_control=False)
    add_layers(m, routes, visible)
    points = [[float(s['latitude']), float(s['longitude'])] for r in routes if r['route_id'] in visible for s in r['stops']]
    if points:
        m.fit_bounds(points, padding=(25, 25))
    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, height=height, key='combined_route_map', returned_objects=[])
    streamlit.caption('R01 파랑 · R02 주황 · 번호: 경유 순서 · 열차: 최종 목적지 · 점선: 미검증 구간')
    if not compact:
        with streamlit.expander('경로 근거 및 미검증 구간'):
            for r in routes:
                streamlit.caption(f"{r['route_id']}: {r['geometry_note']}")
                if r['temporary']:
                    streamlit.warning(f"{r['route_id']}: 최종 트램까지 도로 구간 미확인. 전체 거리·시간 산출 불가.")

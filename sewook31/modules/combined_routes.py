"""Read-only map projection of the legacy R01 preview and registered R02."""
import html

import folium

from modules.independent_routes import RouteStore
from modules.route_engine import calculate_road_route


def route_layers(originals, state, order, destination, allow_network=False):
    lookup = {s['stop_id']: s for s in originals}
    ids = list(order) + [destination]
    points = [[float(lookup[k]['latitude']), float(lookup[k]['longitude'])] for k in ids]
    road = calculate_road_route(points, allow_network=allow_network) if len(points) > 1 else None
    r01 = dict(route_id='R01', name='기존 경유지 노선 (선택 순서 미리보기)',
               stops=[dict(lookup[k], name=lookup[k]['stop_name']) for k in ids],
               paths=[road['coordinates']] if road else [points],
               distance_km=road['distance_km'] if road else None,
               duration_min=road['duration_min'] if road else None,
               temporary=not bool(road), active=True)
    result = [r01]
    for route in state['routes']:
        own = {s['stop_id']: s for s in state['stops'] if s['route_id'] == route['route_id']}
        own.update({k: dict(s, name=s['stop_name']) for k, s in lookup.items() if k == route['transfer_stop_id']})
        route_ids = route['stop_order'] + ([route['transfer_stop_id']] if route['transfer_stop_id'] else [])
        stops = [own[k] for k in route_ids if k in own]
        segments = sorted([s for s in state['segments'] if s['route_id'] == route['route_id']], key=lambda s: s['position'])
        complete = (route['calculation_status'] == 'calculated' and len(stops) >= 2
                    and len(segments) == len(route_ids)-1
                    and all(s['origin'] == a and s['destination'] == b and len(s['coordinates']) >= 2
                            for s, a, b in zip(segments, route_ids, route_ids[1:])))
        result.append(dict(route_id=route['route_id'], name=route['name'], stops=stops,
            paths=[s['coordinates'] for s in segments] if complete else [[[s['latitude'], s['longitude']] for s in stops]],
            distance_km=sum(s['distance_km'] for s in segments) if complete else None,
            duration_min=sum(s['duration_min'] for s in segments) if complete else None,
            temporary=not complete, active=route['active']))
    return result


def add_layers(map_object, routes, visible):
    for route in routes:
        rid = route['route_id']
        color = '#2563eb' if rid == 'R01' else '#dc2626'
        layer = folium.FeatureGroup(name=f"{rid} · {route['name']}", show=rid in visible)
        for stop in route['stops']:
            label = html.escape(f"{stop['name']} ({stop['stop_id']}) · {rid}")
            folium.CircleMarker([float(stop['latitude']), float(stop['longitude'])], radius=7,
                color=color, fill=True, fill_opacity=.85, tooltip=label, popup=label).add_to(layer)
        status = '임시 연결선 · 실제 도로 경로 미확인' if route['temporary'] else 'OSRM 도로 경로 · 실측 아님'
        for path in route['paths']:
            if len(path) >= 2:
                folium.PolyLine(path, color=color, weight=5, dash_array='8,8' if route['temporary'] else None,
                    tooltip=f'{rid} · {status}').add_to(layer)
        layer.add_to(map_object)


def show_combined_map():
    import streamlit as streamlit
    from streamlit_folium import st_folium
    from modules.session_ui import persistent_ui as st
    from modules.map_background import background_map

    store = RouteStore()
    originals = store.original_loader()
    drt = [s['stop_id'] for s in originals if s['stop_type'] == 'drt']
    trams = [s['stop_id'] for s in originals if s['stop_type'] == 'tram']
    streamlit.subheader('R01·R02 통합 운행 지도')
    visible = st.multiselect('표시할 노선', ['R01', 'R02'], default=['R01', 'R02'], key='combined_visible')
    order = st.multiselect('R01 경유 정류장 (선택 순서)', drt, default=drt, key='combined_order')
    destination = st.selectbox('R01 트램 환승 거점', trams, key='combined_tram')
    online = st.checkbox('R01 OSRM 온라인 조회 허용', value=False, key='combined_online')
    routes = route_layers(originals, store.snapshot(), order, destination, online)
    streamlit.caption('R01은 기존 CSV 경유지 기능의 화면 식별자이며 선택 순서 미리보기입니다. R02는 SQLite에 저장된 독립 노선입니다.')
    map_object = background_map([37.474, 127.143], zoom_start=14, layer_control=False)
    add_layers(map_object, routes, visible)
    bounds = [[float(s['latitude']), float(s['longitude'])] for r in routes for s in r['stops'] if r['route_id'] in visible]
    if bounds:
        map_object.fit_bounds(bounds, padding=(25, 25))
    folium.LayerControl(collapsed=False).add_to(map_object)
    st_folium(map_object, height=550, key='combined_route_map', returned_objects=[])
    for route in routes:
        cols = streamlit.columns(3)
        cols[0].metric(route['route_id'], '선택 순서 미리보기' if route['route_id'] == 'R01' else ('활성' if route['active'] else '비활성'))
        cols[1].metric('거리', f"{route['distance_km']:.3f} km" if route['distance_km'] is not None else '미확인')
        cols[2].metric('예상 운행시간', f"{route['duration_min']:.1f} 분" if route['duration_min'] is not None else '미확인')
        if route['temporary']:
            streamlit.warning(f"{route['route_id']}: 임시 연결선입니다. 도로 거리·시간을 추정해 채우지 않습니다.")
        elif not route['active']:
            streamlit.info(f"{route['route_id']}: 저장된 도로 경로를 표시합니다. 차량 설정·활성화 전에는 자동 배차하지 않습니다.")

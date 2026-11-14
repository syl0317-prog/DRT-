"""Read-only, evidence-based fixed stop order and sequential road geometry."""
import hashlib
import json
import math
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import transform

from modules.fixed_routes import DESTINATIONS, resolve_stop
from modules.independent_routes import RouteError
from modules.settings import PROJECT_DIR

R01_ORDER = ('D01', 'D02', 'D03', 'D04')
ARCHIVE = PROJECT_DIR / 'drt_system/data/osrm_cache.json'
PROJECT = Transformer.from_crs(4326, 32652, always_xy=True).transform
UNPROJECT = Transformer.from_crs(32652, 4326, always_xy=True).transform


def valid_road(road):
    try:
        source=str(road.get('source','')).lower()
        return (('osrm' in source or source.startswith('test')) and 'experimental' not in source and len(road['coordinates']) >= 2
            and all(len(p)==2 and all(math.isfinite(float(v)) for v in p)
                    and 37 < float(p[0]) < 38 and 127 < float(p[1]) < 128 for p in road['coordinates'])
            and math.isfinite(float(road['distance_km'])) and float(road['distance_km']) > 0
            and math.isfinite(float(road['duration_min'])) and float(road['duration_min']) > 0)
    except (KeyError, ValueError, TypeError):
        return False


def geometry_check(road, stops):
    """Check order and snap distances without inventing stop-access road edges."""
    if not valid_road(road):
        return None
    line=transform(PROJECT,LineString([(float(lon),float(lat)) for lat,lon in road['coordinates']]))
    distances=[]; positions=[]; access=[]
    for stop in stops:
        pt=Point(*PROJECT(float(stop['longitude']),float(stop['latitude'])))
        positions.append(line.project(pt)); distances.append(line.distance(pt))
        nearest=line.interpolate(positions[-1])
        # Nearest road point is only a dashed access indication, not a new edge.
        anchor_lon,anchor_lat=UNPROJECT(nearest.x,nearest.y)
        access.append({'stop_id':stop['stop_id'],'snap_m':distances[-1],
            'coordinates':[[anchor_lat,anchor_lon],[float(stop['latitude']),float(stop['longitude'])]]})
    if any(d>100 for d in distances) or any(b<=a for a,b in zip(positions,positions[1:])):
        return None
    return {'snap_distances_m':distances,'positions_m':positions,'access':access}


def route_plans(originals,state,archive=None):
    lookup={s['stop_id']:dict(s,name=s['stop_name']) for s in originals}
    lookup.update({s['stop_id']:s for s in state['stops']})
    plans=[]
    for rid,target in DESTINATIONS.items():
        registered=next((r for r in state['routes'] if r['route_id']==rid),None)
        ids=list(R01_ORDER) if rid=='R01' else list(registered['stop_order']) if registered else []
        if len(ids)!=4 or len(set(ids))!=4:
            raise RouteError(f'{rid}: 고정 경유 정류장 4개의 방문 순서를 확인하세요.')
        for sid in ids:
            if resolve_stop(originals,state,sid)!=(rid,target):
                raise RouteError(f'{rid}: 정류장 소속과 고정 목적지가 일치하지 않습니다.')
        order=ids+[target]; stops=[lookup[k] for k in order]
        paths=[]; estimated=[]; access=[]; segments=[]; evidence=[]
        if rid=='R01':
            try:
                cache=json.loads(Path(archive or ARCHIVE).read_text(encoding='utf-8'))
            except (OSError,ValueError):
                cache={}
            key='driving|'+';'.join(f"{float(s['longitude']):.7f},{float(s['latitude']):.7f}" for s in stops)
            road=cache.get(key)
            checked=geometry_check(road,stops) if road else None
            if checked:
                paths=[road['coordinates']];access=checked['access']
                evidence=[dict(source=str(Path(archive or ARCHIVE).relative_to(PROJECT_DIR)) if Path(archive or ARCHIVE).is_relative_to(PROJECT_DIR) else 'test archive',
                    retrieved_at=road.get('retrieved_at','미기록'),**{k:v for k,v in checked.items() if k!='access'})]
            else:
                estimated=[[[float(a['latitude']),float(a['longitude'])],[float(b['latitude']),float(b['longitude'])]] for a,b in zip(stops,stops[1:])]
        else:
            for position,(a,b) in enumerate(zip(stops,stops[1:]),1):
                matches=[s for s in state['segments'] if s['route_id']==rid and s['origin']==a['stop_id'] and s['destination']==b['stop_id']]
                segment=matches[0] if len(matches)==1 else None
                checked=geometry_check(segment,[a,b]) if segment else None
                if checked and (not paths or math.dist(paths[-1][-1],segment['coordinates'][0])<.00001):
                    paths.append(segment['coordinates']);segments.append(segment);access.extend(checked['access'])
                else:
                    estimated.append([[float(a['latitude']),float(a['longitude'])],[float(b['latitude']),float(b['longitude'])]])
        # Adjacent validated segments form one continuous line, not four spokes.
        merged=[]
        for path in paths:
            if merged and math.dist(merged[-1][-1],path[0])<.00001:
                merged[-1].extend(path[1:])
            else:
                merged.append(list(path))
        unique_access={a['stop_id']:a for a in access}
        road_complete=bool(paths) and not estimated
        timing_evidence={k:road.get(k) for k in ('duration_min','distance_km','source','retrieved_at')} if rid=='R01' and road_complete else [
            {k:s.get(k) for k in ('origin','destination','duration_min','distance_km','source','retrieved_at')} for s in segments]
        signature=hashlib.sha256(json.dumps([rid,order,[[s['latitude'],s['longitude']] for s in stops],paths,estimated,timing_evidence],sort_keys=True).encode()).hexdigest()
        plans.append(dict(route_id=rid,name='고정 순차 경유 노선',order=order,stops=stops,paths=merged,
            estimated_paths=estimated,access=list(unique_access.values()),temporary=bool(estimated),
            road_complete=road_complete,signature=signature,segments=segments,evidence=evidence,
            distance_km=float(road['distance_km']) if rid=='R01' and road_complete else sum(s['distance_km'] for s in segments) if road_complete else None,
            duration_min=float(road['duration_min']) if rid=='R01' and road_complete else sum(s['duration_min'] for s in segments) if road_complete else None,
            active=bool(registered and registered['active'] and registered.get('transfer_stop_id')==target and registered['calculation_status']=='calculated'),vehicles=registered['vehicles'] if registered else [],
            test_geometry=any(str(s.get('source','')).lower().startswith('test') for s in segments) or (rid=='R01' and road_complete and str(road.get('source','')).lower().startswith('test')),
            geometry_note=' → '.join(order)+' · 저장 OSRM 도로 모형, 정류장 접근은 별도 검증'))
    return plans

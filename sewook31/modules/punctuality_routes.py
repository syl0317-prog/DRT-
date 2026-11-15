"""Single R01~R04 source shared by every punctuality view and script.

Stops, visit order and final destination come from ``sequential_routes.route_plans``,
the same plans the operating web uses for maps, booking and dispatch. Ride time is
the in-vehicle time from a boarding stop to the route's final destination:

* single stored OSRM road model (R01, R03, R04): route duration split in proportion
  to each stop's projected position along that road line;
* stored per-segment road models (R02): sum of the remaining segment durations.

Legs without a validated road model are returned with ``ride_min=None`` and never
filled with an invented time. Results are research inputs, not observed operation.
"""
import math

from modules.settings import setting
from modules.stop_labels import CANDIDATE_NAMES  # presentation-only review names (명칭 후보 · 현장 미검증)

STATUS_OK = '계산 가능'
STATUS_MISSING = '계산 불가'


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _single_road(plan):
    """Return road dict when one continuous stored road covers the whole route."""
    if len(plan.get('paths') or []) != 1 or plan.get('estimated_paths'):
        return None
    duration = _number(plan.get('duration_min'))
    distance = _number(plan.get('distance_km'))
    if not duration or duration <= 0 or not distance or distance <= 0:
        return None
    evidence = (plan.get('evidence') or [{}])[0]
    return dict(coordinates=plan['paths'][0], duration_min=duration, distance_km=distance,
                source='osrm', retrieved_at=evidence.get('retrieved_at', '미기록'))


def _proportional(plan, road):
    from modules.sequential_routes import geometry_check
    checked = geometry_check(road, plan['stops'])
    if not checked:
        return None
    positions = checked['positions_m']
    total = positions[-1] - positions[0]
    if total <= 0:
        return None
    return [road['duration_min'] * (positions[-1] - p) / total for p in positions[:-1]]


def _segment_sums(plan, allow_network):
    """Remaining-segment sums; a missing segment invalidates every stop before it."""
    from modules.route_engine import calculate_road_route
    stops = plan['stops']
    known = {(s['origin'], s['destination']): _number(s.get('duration_min')) for s in plan.get('segments') or []}
    legs = []
    for a, b in zip(stops, stops[1:]):
        duration = known.get((a['stop_id'], b['stop_id']))
        if duration is None:
            try:
                route = calculate_road_route([[float(a['latitude']), float(a['longitude'])],
                                              [float(b['latitude']), float(b['longitude'])]],
                                             allow_network=allow_network)
            except (TypeError, ValueError, OSError):
                route = None
            duration = _number(route.get('duration_min')) if route else None
        legs.append(duration if duration and duration > 0 else None)
    remaining, total = [], 0.0
    for duration in reversed(legs):
        total = None if total is None or duration is None else total + duration
        remaining.append(total)
    missing = [f"{a['stop_id']}→{b['stop_id']}" for (a, b), d in zip(zip(stops, stops[1:]), legs) if d is None]
    return list(reversed(remaining)), missing


def plan_legs(plan, allow_network=False, dwell_min=None):
    """Boarding-stop → final-destination ride legs for one route plan."""
    dwell = float(setting('dwell_minutes') if dwell_min is None else dwell_min)
    stops = plan['stops']
    destination = stops[-1]
    road = _single_road(plan)
    road_min, missing = None, []
    if road:
        road_min = _proportional(plan, road)
        method = 'OSRM 노선 도로 모형 · 정류장 투영 거리 비례 배분'
        retrieved_at = road['retrieved_at']
        if road_min is None:
            missing = ['정류장이 도로 모형에서 100m 이상 떨어졌거나 순서가 맞지 않음']
    if road_min is None and not road:
        road_min, missing = _segment_sums(plan, allow_network)
        method = 'OSRM 구간 도로 모형 합계'
        retrieved_at = ', '.join(sorted({str(s.get('retrieved_at', '미기록')) for s in plan.get('segments') or []})) or '미기록'
    if road_min is None:
        road_min = [None] * (len(stops) - 1)
    if road and plan.get('route_id') in ('R03', 'R04'):
        method += ' · 차량 접근·정차 검증 필요'
    legs = []
    for index, stop in enumerate(stops[:-1]):
        later_stops = len(stops) - 2 - index  # intermediate boarding stops still to serve
        base = road_min[index]
        ride = None if base is None else base + later_stops * dwell
        legs.append(dict(
            route_id=plan['route_id'], route_name=plan.get('name', ''),
            stop_id=stop['stop_id'], stop_name=CANDIDATE_NAMES.get(stop['stop_id']) or stop.get('name') or stop.get('stop_name') or stop['stop_id'],
            position=index + 1, latitude=_number(stop.get('latitude')), longitude=_number(stop.get('longitude')),
            destination_id=destination['stop_id'],
            destination_name=destination.get('name') or destination.get('stop_name') or destination['stop_id'],
            destination_latitude=_number(destination.get('latitude')),
            destination_longitude=_number(destination.get('longitude')),
            road_min=base, dwell_min=later_stops * dwell, ride_min=ride,
            status=STATUS_OK if ride is not None else STATUS_MISSING,
            method=method, retrieved_at=retrieved_at,
            source=f"{method} · 중간 정차 {later_stops}회×{dwell:g}분 포함 · 실측 아님",
            missing=', '.join(missing) if ride is None else ''))
    return legs


def label(leg):
    return f"{leg['route_id']} · {leg['stop_name']} ({leg['stop_id']})"


def route_legs(allow_network=False, plans=None):
    """All R01~R04 legs plus route-level problems, from the operating web's plans."""
    problems = []
    if plans is None:
        from modules.independent_routes import RouteStore, read_original_stops
        from modules.sequential_routes import route_plans
        try:
            plans = route_plans(read_original_stops(), RouteStore().snapshot())
        except (ValueError, KeyError, OSError) as error:
            return [], [f'운영 노선 정보를 읽지 못했습니다: {error}']
    legs = []
    for plan in plans:
        try:
            legs.extend(plan_legs(plan, allow_network))
        except (ValueError, KeyError, TypeError) as error:
            problems.append(f"{plan.get('route_id', '?')}: {error}")
    for leg in legs:
        if leg['status'] == STATUS_MISSING:
            problems.append(f"{label(leg)}: 도로 모형 미확인({leg['missing'] or '경로 없음'}) · 정시성 계산 제외")
    return legs, problems

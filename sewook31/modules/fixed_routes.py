"""Fixed operating policy; source registries remain unchanged."""
from modules.independent_routes import RouteError

COLORS = {"R01": "#2563EB", "R02": "#F97316"}
DESTINATIONS = {"R01": "T01", "R02": "T02"}


def resolve_stop(originals, state, stop_id):
    # R01 is the existing CSV route namespace; R02 membership comes from registry.
    candidates = set()
    if any(s["stop_id"] == stop_id and s["stop_type"] == "drt" for s in originals):
        candidates.add("R01")
    candidates.update(r["route_id"] for r in state["routes"] if stop_id in r["stop_order"])
    candidates.update(s["route_id"] for s in state["stops"] if s["stop_id"] == stop_id)
    if len(candidates) != 1 or not candidates <= DESTINATIONS.keys():
        raise RouteError(f"{stop_id}: 노선 소속이 없거나 중복됩니다. 등록부를 확인하세요: {sorted(candidates)}")
    route_id = candidates.pop()
    destination = DESTINATIONS[route_id]
    if not any(s["stop_id"] == destination and s["stop_type"] == "tram" for s in originals):
        raise RouteError(f"{route_id}: 고정 트램 거점 {destination} 데이터가 없습니다.")
    return route_id, destination

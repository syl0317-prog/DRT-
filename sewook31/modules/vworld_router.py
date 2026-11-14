"""Independent endpoint routing. Coordinates are always (latitude, longitude)."""
import hashlib
import json
import math
from pathlib import Path

import networkx as nx
from modules.vworld_graph import GEOD


def _yes(value):
    return value is True or str(value).lower() == "true"


def _point(value):
    if len(value) != 2:
        raise ValueError("Expected (latitude, longitude)")
    lat, lon = map(float, value)
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid latitude/longitude")
    return lat, lon


def _distance(a, b):
    return abs(GEOD.inv(a[1], a[0], b[1], b[0])[2])


class VWorldRouter:
    """Node snap only; no new junctions, edge entry points, or graph mutations.

    Future verified data contract (relative to geometry coordinate order):
    edge direction=forward/reverse/both, direction_verified=True,
    direction_evidence=<nonempty reference>; both endpoints require
    connectivity_verified=True, connectivity_evidence=<reference>.
    Snapped nodes additionally require access_verified and access_evidence.
    These are explicit attestations, not independently authenticated by this code.
    Current stage-one files contain none of these attestations.
    """
    def __init__(self, graph, source="in-memory test graph"):
        self.graph = graph.copy()
        self.source = source

    @classmethod
    def from_graphml(cls, path):
        path = Path(path)
        graph = nx.read_graphml(path, force_multigraph=True)
        return cls(graph, dict(file_name=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    def _node_point(self, node):
        d = self.graph.nodes[node]
        return float(d["latitude"]), float(d["longitude"])

    def _snap(self, point):
        if not self.graph:
            return None
        distance, _, node = min((_distance(point, self._node_point(n)), str(n), n) for n in self.graph)
        return dict(node_id=node, distance_m=distance, coordinate_lat_lon=list(self._node_point(node)))

    def route(self, origin, destination, mode="verified", max_snap_m=100):
        """Return a structured success/failure, not an asserted drivable route.

        Distance on roads excludes straight-line connectors. Scenarios use only
        road distance; connector travel time cannot be established by this graph.
        """
        result = dict(success=False, mode=mode, validation_status="experimental" if mode == "experimental" else "not_verified",
            source=self.source, speed_source="assumption; no GITS or OSRM values", snap_method="nearest_node",
            route_geojson=None, scenarios=[], reason=None)
        def fail(reason):
            result["reason"] = reason
            return result
        if mode not in ("verified", "experimental"):
            return fail("invalid_mode")
        try:
            origin, destination = _point(origin), _point(destination)
            limit = float(max_snap_m)
            if not math.isfinite(limit) or limit < 0:
                return fail("invalid_snap_limit")
        except (TypeError, ValueError, OverflowError):
            return fail("invalid_coordinates_or_snap_limit")
        start, end = self._snap(origin), self._snap(destination)
        result.update(origin_snap=start, destination_snap=end)
        if start is None:
            return fail("empty_graph")
        if start["distance_m"] > limit:
            return fail("origin_snap_too_far")
        if end["distance_m"] > limit:
            return fail("destination_snap_too_far")
        a, b = start["node_id"], end["node_id"]
        if not nx.has_path(self.graph.to_undirected(), a, b):
            return fail("different_geometric_components")
        eligible = nx.MultiDiGraph()
        eligible.add_nodes_from(self.graph.nodes)
        blocked = 0
        for u, v, key, attrs in self.graph.edges(keys=True, data=True):
            try:
                length = float(attrs["length_m"])
                geom = json.loads(attrs["geometry_json"])["coordinates"]
                coords = [[float(p[0]), float(p[1])] for p in geom]
                if len(coords) < 2 or not math.isfinite(length) or length <= 0:
                    raise ValueError()
                if tuple(coords[0]) != tuple(reversed(self._node_point(u))):
                    u, v = v, u
                if tuple(coords[0]) != tuple(reversed(self._node_point(u))) or tuple(coords[-1]) != tuple(reversed(self._node_point(v))):
                    raise ValueError()
            except (KeyError, TypeError, ValueError, IndexError):
                blocked += 1
                continue
            directions = ("forward", "reverse")
            if mode == "verified":
                ok = (_yes(attrs.get("direction_verified")) and attrs.get("direction_evidence") and
                      all(_yes(self.graph.nodes[n].get("connectivity_verified")) and
                          self.graph.nodes[n].get("connectivity_evidence") for n in (u, v)))
                direction = attrs.get("direction")
                if not ok or direction not in ("forward", "reverse", "both"):
                    blocked += 1
                    continue
                directions = ("forward", "reverse") if direction == "both" else (direction,)
            for direction in directions:
                x, y = (u, v) if direction == "forward" else (v, u)
                eligible.add_edge(x, y, key=key, **dict(attrs, length_m=length,
                    oriented_coordinates=coords if direction == "forward" else list(reversed(coords))))
        result["blocked_edge_count"] = blocked
        if mode == "verified":
            if eligible.number_of_edges() == 0:
                return fail("no_verified_direction_and_connectivity_links")
            if not all(_yes(self.graph.nodes[n].get("access_verified")) and
                       self.graph.nodes[n].get("access_evidence") for n in (a, b)):
                return fail("origin_or_destination_access_unverified")
        try:
            path = nx.shortest_path(eligible, a, b, weight="length_m")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return fail("no_path_in_selected_mode")
        traversals, coordinates = [], []
        for u, v in zip(path, path[1:]):
            key, edge = min(eligible[u][v].items(), key=lambda item: (item[1]["length_m"], str(item[0])))
            coords = edge["oriented_coordinates"]
            coordinates.extend(coords if not coordinates else coords[1:])
            traversals.append(dict(edge_id=str(key), link_id=edge.get("link_id", ""), road_name=edge.get("road_name", ""),
                length_m=edge["length_m"], from_node=u, to_node=v))
        # Remove repeated adjacent vertices without discarding parallel links.
        coordinates = [p for i, p in enumerate(coordinates) if i == 0 or p != coordinates[i-1]]
        distance = sum(e["length_m"] for e in traversals)
        status = "experimental" if mode == "experimental" else "verified_input_evidence"
        geometry = dict(type="LineString", coordinates=coordinates) if len(coordinates) >= 2 else dict(
            type="Point", coordinates=list(reversed(self._node_point(a))))
        result.update(success=True, reason="same_snapped_node" if a == b else "path_found",
            validation_status=status, node_ids=path, traversals=traversals,
            link_ids=[e["link_id"] for e in traversals], road_distance_m=distance,
            connector_distance_m=start["distance_m"]+end["distance_m"],
            distance_including_straight_connectors_m=distance+start["distance_m"]+end["distance_m"],
            route_geojson=dict(type="Feature", geometry=geometry, properties=dict(
                validation_status=status, road_distance_m=distance, link_ids=[e["link_id"] for e in traversals])),
            assumptions=["Nearest node access is assumed in experimental mode.",
                "Experimental mode treats all retained edges as bidirectional; actual driving legality unverified.",
                "No interior crossings or T junctions added; connector lines are not road paths."] if mode == "experimental" else [])
        if mode == "experimental":
            result["scenarios"] = [dict(road_distance_m=distance, assumed_speed_kmh=speed,
                assumed_travel_time_min=distance/1000/speed*60, source="constant speed assumption; not observed; not OSRM",
                validation_status="experimental", connector_time_included=False) for speed in (15, 20, 25)]
        return result

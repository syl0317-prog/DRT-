"""Endpoint-only geometric topology. This undirected graph is NOT a driving network."""
import hashlib
import json
import math
import platform
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import networkx as nx
import pyproj
import shapely
from pyproj import Geod
from shapely.geometry import LineString, Point, mapping
from shapely.strtree import STRtree

GEOD = Geod(ellps="WGS84")


def build_graph(collection):
    """Return a MultiGraph and audit; merge only exactly equal XY endpoints.

    Multipart lines remain independent parts. Z is retained in geometry but is
    not evidence of level connectivity. Even equal endpoints are only candidates.
    No source attribute is interpreted as a verified direction.
    """
    graph = nx.MultiGraph(topology_only=True, routing_permitted=False,
                          direction_policy="unknown; no driving permission inferred")
    nodes, issues, segments = {}, [], []
    features = collection.get("features", [])
    for fi, feature in enumerate(features):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        kind, coords = geom.get("type"), geom.get("coordinates")
        if kind not in ("LineString", "MultiLineString") or not coords:
            issues.append(dict(feature_index=fi, reason="unsupported_or_empty_geometry"))
            continue
        parts = [coords] if kind == "LineString" else coords
        for pi, part in enumerate(parts):
            try:
                if len(part) < 2 or any(len(p) < 2 or not all(math.isfinite(float(v)) for v in p)
                                       or not -180 <= p[0] <= 180 or not -90 <= p[1] <= 90 for p in part):
                    raise ValueError("invalid coordinates")
                xy = [(float(p[0]), float(p[1])) for p in part]
                line = LineString(xy)
                length = GEOD.line_length([p[0] for p in xy], [p[1] for p in xy])
                if length <= 0:
                    raise ValueError("zero length")
            except (TypeError, ValueError, OverflowError):
                issues.append(dict(feature_index=fi, part_index=pi, reason="invalid_or_zero_length_part"))
                continue
            edge_id = f"f{fi}_p{pi}"
            for point in (xy[0], xy[-1]):
                if point not in nodes:
                    nodes[point] = f"n{len(nodes)}"
                    graph.add_node(nodes[point], longitude=point[0], latitude=point[1])
            warnings = []
            if any(a == b for a, b in zip(xy, xy[1:])):
                warnings.append("consecutive_duplicate_coordinates")
            if not line.is_simple:
                warnings.append("self_intersection")
            if xy[0] == xy[-1]:
                warnings.append("closed_part")
            if any(len(p) > 2 for p in part):
                warnings.append("extra_coordinate_dimensions_not_used_for_topology")
            for warning in warnings:
                issues.append(dict(feature_index=fi, part_index=pi, reason=warning))
            attrs = dict(edge_id=edge_id, feature_index=fi, part_index=pi,
                         link_id=str(props.get("link_id", "")), road_name=str(props.get("road_name", "")),
                         direction="unknown", length_m=length,
                         source_properties_json=json.dumps(props, ensure_ascii=False),
                         geometry_json=json.dumps(dict(type="LineString", coordinates=part)),
                         warnings_json=json.dumps(warnings))
            # Preserve arbitrary properties without GraphML type coercion or name collisions.
            for name in ("rd_rank_h", "rd_type_h", "max_spd", "rest_veh_h", "rest_w", "rest_h"):
                attrs[name] = str(props.get(name, ""))
            graph.add_edge(nodes[xy[0]], nodes[xy[-1]], key=edge_id, **attrs)
            segments.append((edge_id, line))

    components = sorted(nx.connected_components(graph), key=lambda c: (-len(c), min(c)))
    component_rows = []
    for ci, members in enumerate(components):
        component_id = f"c{ci}"
        for node in members:
            graph.nodes[node]["component_id"] = component_id
        sub = graph.subgraph(members)
        component_rows.append(dict(component_id=component_id, node_count=len(members),
            edge_count=sub.number_of_edges(), length_m=sum(d["length_m"] for *_, d in sub.edges(data=True)),
            edge_ids=[d["edge_id"] for *_, d in sub.edges(data=True)]))
    # Exact geometric intersections are review candidates, never inserted nodes.
    candidates = []
    lines = [line for _, line in segments]
    tree = STRtree(lines)
    for i, (eid, line) in enumerate(segments):
        for j in tree.query(line):
            j = int(j)
            if j <= i:
                continue
            other = lines[j]
            intersection = line.intersection(other)
            if intersection.is_empty:
                continue
            points = [intersection] if intersection.geom_type == "Point" else list(intersection.geoms) if intersection.geom_type == "MultiPoint" else []
            if not points:
                candidates.append(dict(edge_ids=[eid, segments[j][0]], kind="overlap_or_complex_intersection", geometry=mapping(intersection)))
            for p in points:
                a = p.equals(Point(line.coords[0])) or p.equals(Point(line.coords[-1]))
                b = p.equals(Point(other.coords[0])) or p.equals(Point(other.coords[-1]))
                if a and b:
                    continue
                candidates.append(dict(edge_ids=[eid, segments[j][0]],
                    kind="endpoint_interior" if a or b else "interior_crossing",
                    geometry=mapping(p)))
    report = dict(graph_semantics="undirected geometric candidate topology; not legal driving connectivity",
        node_count=graph.number_of_nodes(), edge_count=graph.number_of_edges(),
        feature_count=len(features), component_count=len(components), components=component_rows,
        total_length_m=sum(d["length_m"] for *_, d in graph.edges(data=True)),
        dead_end_node_ids=[n for n, degree in graph.degree() if degree == 1],
        isolated_node_ids=list(nx.isolates(graph)), self_loop_count=nx.number_of_selfloops(graph),
        issues=issues, issue_counts=dict(Counter(x["reason"] for x in issues)),
        intersection_candidates=candidates, intersection_candidate_counts=dict(Counter(x["kind"] for x in candidates)),
        limitations=["Exact XY endpoints only; endpoint connections remain unverified.",
            "No snapping, splitting, turn restrictions or direction inference.",
            "Crossings and T junctions need level/access evidence before connection.",
            "Degree-zero nodes cannot reveal missing roads in an endpoint-derived graph.",
            "Smaller components are disconnected from the largest, not necessarily erroneous."])
    return graph, report


def save_build(source, output_root):
    """Create a unique, exclusive run directory; never overwrite previous runs."""
    source = Path(source)
    raw = source.read_bytes()
    collection = json.loads(raw.decode("utf-8-sig"))
    graph, report = build_graph(collection)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid4().hex
    directory = Path(output_root) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    def write(name, value):
        with (directory / name).open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
    nx.write_graphml(graph, directory / "vworld_graph.graphml")
    write("vworld_nodes.geojson", dict(type="FeatureCollection", features=[
        dict(type="Feature", id=n, geometry=dict(type="Point", coordinates=[d["longitude"], d["latitude"]]),
             properties=dict(node_id=n, degree=graph.degree(n), **d)) for n, d in graph.nodes(data=True)]))
    write("vworld_edges.geojson", dict(type="FeatureCollection", features=[
        dict(type="Feature", id=k, geometry=json.loads(d["geometry_json"]),
             properties=dict(source_node=u, target_node=v, component_id=graph.nodes[u]["component_id"],
                             **{a: b for a, b in d.items() if a != "geometry_json"},
                             source_properties=json.loads(d["source_properties_json"])))
        for u, v, k, d in graph.edges(keys=True, data=True)]))
    write("connectivity_report.json", report)
    write("build_metadata.json", dict(run_id=run_id, created_at_utc=datetime.now(timezone.utc).isoformat(),
        source_name=source.name, source_sha256=hashlib.sha256(raw).hexdigest(),
        source_crs=collection.get("crs"), interpreted_crs="WGS84 lon/lat; source CRS provenance requires verification",
        length_method="pyproj.Geod WGS84 ellipsoid, XY only", python=platform.python_version(),
        versions=dict(networkx=nx.__version__, pyproj=pyproj.__version__, shapely=shapely.__version__),
        implementation_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        policy=dict(endpoint_merge="exact XY", automatic_intersection_split=False, direction="unknown", routing_permitted=False)))
    return directory, report

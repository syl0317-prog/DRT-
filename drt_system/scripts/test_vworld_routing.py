"""Offline example runner. All coordinates use latitude longitude order."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from uuid import uuid4

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.vworld_router import VWorldRouter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--origin", nargs=2, type=float, metavar=("LAT", "LON"), default=[37.4783405, 127.1437479])
    parser.add_argument("--destination", nargs=2, type=float, metavar=("LAT", "LON"), default=[37.47, 127.15])
    parser.add_argument("--max-snap-m", type=float, default=100)
    args = parser.parse_args()
    graphs = sorted((BASE/"data/derived").glob("*/vworld_graph.graphml"))
    if args.graph is None and not graphs:
        parser.error("No GraphML found; build stage-one graph first")
    graph_file = args.graph or graphs[-1]
    router = VWorldRouter.from_graphml(graph_file)
    results = {mode: router.route(args.origin, args.destination, mode, args.max_snap_m)
               for mode in ("verified", "experimental")}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")+"_"+uuid4().hex
    out = BASE/"data/derived"/run_id
    out.mkdir(parents=True, exist_ok=False)
    payload = dict(run_id=run_id, origin_lat_lon=args.origin, destination_lat_lon=args.destination,
                   max_snap_m=args.max_snap_m, graph_source=router.source, results=results,
                   implementation_sha256=hashlib.sha256((BASE/"modules/vworld_router.py").read_bytes()).hexdigest())
    with (out/"vworld_routing_results.json").open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
    summary = {mode: {key: result.get(key) for key in
        ("success", "reason", "validation_status", "road_distance_m", "connector_distance_m", "scenarios")}
        for mode, result in results.items()}
    print(json.dumps(dict(output_directory=str(out), results=summary), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

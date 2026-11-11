"""Run from any working directory; existing app modules are not imported."""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.vworld_graph import save_build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=BASE.parent / "data/vworld/wirye_road_links.geojson")
    parser.add_argument("--output-root", type=Path, default=BASE / "data/derived")
    args = parser.parse_args()
    directory, report = save_build(args.source, args.output_root)
    print(json.dumps(dict(output_directory=str(directory), **{key: report[key] for key in
        ("node_count", "edge_count", "component_count", "issue_counts", "intersection_candidate_counts")}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Run from any directory; create separate review artifacts without touching inputs."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "drt_system"))
from modules.gits_vworld_map import run

if __name__ == "__main__":
    directory, summary = run(ROOT)
    print(json.dumps(dict(output_directory=str(directory), summary=summary), ensure_ascii=False, indent=2))

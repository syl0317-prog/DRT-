"""Offline V-World / GITS evidence audit; never overwrite existing outputs."""
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from modules.gits_validation import run_audit

if __name__ == "__main__":
    out, report = run_audit(BASE.parent)
    print(json.dumps(dict(output_directory=str(out), **report), ensure_ascii=True, indent=2))

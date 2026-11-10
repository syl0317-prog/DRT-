"""Read-only schema audit; never prints credentials or API payloads."""
import hashlib
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    protected = list((ROOT/'data/raw').rglob('*')) + list(ROOT.rglob('*.geojson')) + [ROOT/'sewook31/data/drt_stops.csv', ROOT/'data/processed/위례_DRT_GITS_도로교통정보_정리.xlsx']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected if p.is_file()}
    (ROOT/'data/processed/gits_source_hashes.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    for name in ['wirye_traffic_history.csv', 'wirye_speed_raw.csv', 'drt_road_segments.csv', 'wirye_topis_links.csv']:
        p = ROOT/'data/raw'/name
        f = pd.read_csv(p, encoding='utf-8-sig')
        print(name, f.shape, list(f.columns)); print(f.head(3).to_string(index=False))
    p = ROOT/'data/processed/위례_DRT_GITS_도로교통정보_정리.xlsx'
    from gits_xlsx import read_sheets
    for sheet, f in read_sheets(p).items():
        print('SHEET', sheet, f.shape, list(f.columns)); print(f.head(4).to_string(index=False))
    cache = json.loads((ROOT/'sewook31/data/osrm_cache.json').read_text(encoding='utf-8'))
    print('CACHE', len(cache), [list(v.keys()) for v in list(cache.values())[:1]])

"""Create input templates, verify protected sources, test server startup, write audit report."""
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'sewook31'))
from modules.settings import PROJECT_DIR
from modules.operating_costs import cost_table

def run():
    for name, fields in {
        'travel_time_observed.csv': ['측정일', '출발지', '도착지', '실측소요분', 'OSRM소요분', '검증상태', '출처'],
        'household_stats_todo.csv': ['단지코드', '단지명', '확인항목', '값', '출처', '검증상태']}.items():
        path = ROOT/'data/assumptions'/name
        if not path.exists():
            with path.open('w', encoding='utf-8-sig', newline='') as f:
                csv.writer(f).writerow(fields)
    # All edited/new text source uses UTF-8 and LF (avoid CRLF whitespace warnings).
    changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=ROOT).decode('utf-8').splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT).decode('utf-8').splitlines()
    for name in changed+new:
        if name.endswith(('.py', '.md', '.json')) or name == 'docs/관리용 웹사이트 구상':
            path = ROOT/name
            text = '\n'.join(line.rstrip() for line in path.read_text(encoding='utf-8').splitlines())+'\n'
            path.write_text(text, encoding='utf-8', newline='\n')
    # Compare raw bytes against initial commit; git porcelain quotes Unicode paths by default.
    names = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'ls-files'], cwd=ROOT).decode('utf-8').splitlines()
    protected = [n for n in names if n.startswith('data/raw/') or n.endswith('.geojson') or n == 'sewook31/data/drt_stops.csv']
    for name in protected:
        original = subprocess.check_output(['git', 'cat-file', '--filters', '9ab01d9:'+name], cwd=ROOT)
        if (ROOT/name).read_bytes() != original:
            raise RuntimeError('Protected file changed: '+name)
    cost_table(4).to_csv(ROOT/'data/processed/operating_cost_reference.csv', index=False, encoding='utf-8-sig')
    # Cross-check own point-in-polygon code against GEOS, including holes.
    from shapely.geometry import shape, Point
    from build_stage0 import read_csv
    geometry = json.loads((ROOT/'data/processed/wirye_changgok_boundary.geojson').read_text(encoding='utf-8'))['features'][0]['geometry']
    polygon = shape(geometry)
    for row in read_csv(ROOT/'data/processed/apartment_master.csv'):
        if row['경도'] != 'missing':
            point = Point(float(row['경도']), float(row['위도']))
            expected = 'boundary' if polygon.boundary.covers(point) else ('Y' if polygon.contains(point) else 'N')
            assert row['창곡동내부'] == expected
    log = ROOT/'data/processed/streamlit_smoke.log'
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
    with log.open('w', encoding='utf-8') as f:
        process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', str(ROOT/'sewook31/app.py'), '--server.headless=true', '--server.port=18571', '--browser.gatherUsageStats=false'], cwd=ROOT, stdout=f, stderr=f, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        healthy = False
        try:
            for _ in range(20):
                if process.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18571/_stcore/health', timeout=.5) as response:
                        healthy = response.status == 200
                    if healthy:
                        time.sleep(5)
                        break
                except OSError:
                    time.sleep(.5)
        finally:
            process.terminate()
            process.wait(timeout=10)
    if not healthy or 'Traceback' in log.read_text(encoding='utf-8'):
        raise RuntimeError('Streamlit startup failed; see '+str(log))
    print(f'Protected source files unchanged: {len(protected)}; GEOS boundary cross-check PASS; Streamlit HTTP health + 5 seconds PASS')

if __name__ == '__main__':
    run()

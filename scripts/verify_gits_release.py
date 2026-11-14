"""Non-mutating syntax/source/reproducibility/startup checks."""
import hashlib
import json
import os
import py_compile
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    hashes = json.loads((ROOT/'data/processed/gits_source_hashes.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in hashes.items())
    outputs = list((ROOT/'data/processed').glob('gits_*.csv')) + list((ROOT/'data/processed').glob('drt_strategy_*.csv')) + [ROOT/'data/processed/punctuality_gits_results.csv']
    before = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in outputs}
    subprocess.run([sys.executable, str(ROOT/'scripts/run_gits_analysis.py')], check=True)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p,h in before.items())
    with tempfile.TemporaryDirectory() as d:
        for i,p in enumerate(list((ROOT/'sewook31').rglob('*.py')) + list((ROOT/'scripts').glob('*gits*.py'))):
            py_compile.compile(str(p), cfile=str(Path(d)/f'{i}.pyc'), doraise=True)
        with (Path(d)/'server.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable,'-m','streamlit','run',str(ROOT/'sewook31/app.py'),'--server.headless=true','--server.port=18573','--browser.gatherUsageStats=false'], stdout=log, stderr=log, env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            healthy = False
            try:
                for _ in range(30):
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:18573/_stcore/health', timeout=.5) as r:
                            healthy = r.status == 200
                        if healthy:
                            break
                    except OSError:
                        time.sleep(.5)
            finally:
                process.terminate(); process.wait(timeout=10)
            assert healthy
    print(f'PASS: {len(hashes)} protected source hashes; {len(outputs)} byte-identical outputs; syntax; Streamlit HTTP health')

if __name__ == '__main__':
    main()

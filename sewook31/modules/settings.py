"""Project paths and annotated simulation settings."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BASE_DIR.parent
PARAMS_FILE = PROJECT_DIR / 'data' / 'assumptions' / 'sim_params.json'

def load_params():
    return json.loads(PARAMS_FILE.read_text(encoding='utf-8'))

def setting(name):
    return load_params()[name]['value']

def stops_path():
    path = (PROJECT_DIR / 'sewook31' / 'data' / setting('stops_file')).resolve()
    if path.parent != (PROJECT_DIR / 'sewook31' / 'data').resolve() or path.suffix != '.csv':
        raise ValueError('stops_file must be a CSV filename in sewook31/data')
    return path

def vehicle_count():
    import streamlit as st
    return int(st.session_state.get('vehicle_count', setting('vehicle_count')))

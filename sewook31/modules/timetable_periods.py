"""Read historical period files and the current annotated service schema."""
import json
import math
from modules.settings import PROJECT_DIR


def load_periods():
    raw = json.loads((PROJECT_DIR / 'data/assumptions/tram_timetable.json').read_text(encoding='utf-8'))
    if 'service' in raw:
        service = raw['service']
        result = {
            '출퇴근': {'headway_minutes': service['headway_peak']['value'], 'status': service['headway_peak']['status']},
            '평시': {'headway_minutes': service['headway_off_peak']['value'], 'status': service['headway_off_peak']['status']},
        }
    else:
        result = {key: value for key, value in raw.items() if isinstance(value, dict) and 'headway_minutes' in value}
    if not result or any(not isinstance(s['headway_minutes'], (int, float)) or not math.isfinite(s['headway_minutes']) or s['headway_minutes'] <= 0 for s in result.values()):
        raise ValueError('저장된 트램 배차간격이 없거나 유효하지 않습니다.')
    return result

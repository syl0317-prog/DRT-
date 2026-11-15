"""Review names for presentation only; never update catalogs or stored snapshots."""
from types import MappingProxyType


CANDIDATE_NAMES = MappingProxyType({
    'D01': '위례그린파크푸르지오 인근',
    'D02': '위례롯데캐슬 인근',
    'D03': '위례중학교 인근',
    'D04': '위례아이파크2차 인근',
    'V05': '위례호반써밋에비뉴 인근',
    'V06': '위례센트럴푸르지오 인근',
    'V07': '위례새초롱유치원 인근',
    'V08': '위례동행정복지센터 인근',
    'R03-S01': '송파더센트레 인근',
    'R03-S02': '위례포레샤인23단지 인근',
    'R04-S01': '위례31단지 인근',
    'R04-S02': '위례서로·헌릉로 접속부 인근',
})
CANDIDATE_STATUS = '명칭 후보 · 현장 미검증'
LOCATION_REVIEW_IDS = frozenset(('R04-S01', 'R04-S02'))


def stop_label(stop_id, original_name=None):
    """Keep the ID visible; unknown IDs and destination names retain their meaning."""
    candidate = CANDIDATE_NAMES.get(stop_id)
    if candidate is None:
        return f'{original_name} ({stop_id})' if original_name and original_name != stop_id else str(stop_id)
    status = CANDIDATE_STATUS
    if stop_id in LOCATION_REVIEW_IDS:
        status += ' · 위치 검증 필요'
    return f'{candidate} ({stop_id}) · {status}'

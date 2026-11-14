"""Read-only presentation audit. Never changes a stored reservation or status."""
from collections import Counter
from modules.fixed_routes import DESTINATIONS,resolve_stop
from modules.independent_routes import RouteError

ACTIVE={'예약완료','배차 검토 필요'}


def audit_records(records,originals,state):
    rows=[]
    for record in records:
        row=dict(record); reasons=[]
        rid=row.get('route_id');target=DESTINATIONS.get(rid)
        if target is None:
            reasons.append('노선 식별 정보 확인 필요')
        elif row.get('destination_stop')!=target:
            reasons.append(f"{rid}의 고정 하차는 {target}, 저장값은 {row.get('destination_stop')}")
        try:
            actual,_=resolve_stop(originals,state,row.get('boarding_stop'))
            if actual!=rid:
                reasons.append(f'승차 정류장 소속은 {actual}, 저장 노선은 {rid}')
        except RouteError as error:
            reasons.append(str(error))
        booking=row.get('booking_snapshot') or {}
        run=booking.get('run_snapshot') or {}
        source=row.get('source')
        if source=='legacy_csv':
            category='과거 CSV'
        elif source=='route_registry':
            category='연구 등록부'
        elif booking.get('test_only') or run.get('test_only'):
            category='시험 운행편'
        elif row.get('status')=='예약완료' and not (row.get('run_id') and run and run.get('test_only') is False):
            category='과거 연구 배정'
        else:
            category='신규 SQLite'
        original_status=row.get('status')
        if original_status=='예약취소':
            stage='예약 취소'
        elif reasons:
            stage='규칙 불일치 · 확인 필요'
        elif category=='과거 CSV':
            stage='과거 예약 · 운영일 미확인'
        elif category in ('연구 등록부','시험 운행편','과거 연구 배정'):
            stage='연구·시험 배정' if original_status=='예약완료' else '연구·시험 대기'
        elif original_status=='예약완료':
            stage='배차 확정'
        elif original_status=='배차 검토 필요':
            stage='예약 접수 · 배차 대기'
        else:
            stage='상태 확인 필요'
        row.update(data_category=category,policy_valid=not reasons,policy_issues=' / '.join(reasons),display_stage=stage,
            operating_record=category=='신규 SQLite' and not reasons,
            review_reason=' / '.join(reasons) or row.get('dispatch_status') or '배차 근거 확인 필요')
        rows.append(row)
    return rows


def audit_service(service):
    return audit_records(service.list_records(),service.routes.original_loader(),service.routes.snapshot())


def audit_summary(rows):
    current=[r for r in rows if r['operating_record'] and r.get('status') in ACTIVE]
    return dict(total=len(rows),operating=len(current),pending=sum(r['display_stage']=='예약 접수 · 배차 대기' for r in current),
        confirmed=sum(r['display_stage']=='배차 확정' for r in current),
        history=sum(r['data_category']=='과거 CSV' for r in rows),
        research=sum(r['data_category'] in ('연구 등록부','시험 운행편','과거 연구 배정') for r in rows),
        mismatches=sum(not r['policy_valid'] for r in rows),
        active_mismatches=sum(not r['policy_valid'] and r.get('status') in ACTIVE for r in rows))


def safe_counts(rows):
    """Audit report aggregates only; never exports passenger or raw payload data."""
    return dict(audit_summary(rows),by_source=dict(Counter(r.get('source','미기록') for r in rows)),
        invalid_combinations=dict(Counter(f"{r.get('route_id')}→{r.get('destination_stop')} ({r['data_category']})" for r in rows if not r['policy_valid'])))


def display_rows(rows):
    return [{'예약 ID':r['public_id'],'자료 구분':r['data_category'],'노선':r.get('route_id'),'승차':r.get('boarding_stop'),
        '하차':r.get('destination_stop'),'인원':r.get('passengers'),'표시 상태':r['display_stage'],'원본 상태':r.get('status'),
        '승차 시각':r.get('requested_at') or '미기록','차량':r.get('vehicle_id') or '미배정',
        '확인 사항':r['policy_issues'] or (r['review_reason'] if r.get('status')=='배차 검토 필요' else '')} for r in rows]

"""Explicit fleet and dated runs; no vehicles or timetables are inferred."""
from datetime import datetime,timedelta,timezone
import copy,json,math
from uuid import uuid4
from modules.independent_routes import RouteError
from modules.sequential_routes import route_plans
from modules.settings import setting


def ensure_tables(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS fixed_vehicles(vehicle_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    connection.execute('CREATE TABLE IF NOT EXISTS fixed_runs(run_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')


def read_rows(connection,table):
    if table not in ('fixed_runs','fixed_vehicles'):
        raise ValueError('Unknown dispatch table')
    if not connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
        return []
    return [json.loads(r[0]) for r in connection.execute(f'SELECT payload FROM {table}')]


def register_vehicle(service,vehicle_id,capacity,evidence,test_only=False):
    if not str(vehicle_id).strip() or type(capacity) is not int or not 1<=capacity<=100 or not str(evidence).strip():
        raise RouteError('차량 ID·정원·실제 차량 확인 근거가 필요합니다.')
    row=dict(vehicle_id=str(vehicle_id).strip(),capacity=capacity,evidence=str(evidence).strip(),test_only=bool(test_only),available=True)
    with service.transaction() as (connection,state,attached):
        ensure_tables(connection)
        if connection.execute('SELECT 1 FROM fixed_vehicles WHERE vehicle_id=?',(row['vehicle_id'],)).fetchone():
            raise RouteError('이미 등록된 차량 ID입니다. 기존 운행편 보호를 위해 덮어쓰지 않습니다.')
        connection.execute('INSERT INTO fixed_vehicles VALUES(?,?)',(row['vehicle_id'],json.dumps(row,ensure_ascii=False)))
    return row


def register_run(service,route_id,vehicle_id,departure,offsets,access_evidence):
    if not isinstance(departure,datetime) or departure.tzinfo is None or departure<=datetime.now(timezone.utc):
        raise RouteError('시간대가 있는 미래 출발 시각이 필요합니다.')
    with service.transaction() as (connection,state,attached):
        ensure_tables(connection)
        plan=next((p for p in route_plans(service.routes.original_loader(),state) if p['route_id']==route_id),None)
        if not plan or not plan['road_complete']:
            raise RouteError('최종 트램까지 방향별 전체 도로 경로가 확인되지 않아 운행편을 등록할 수 없습니다.')
        if route_id=='R02' and not plan['active']:
            raise RouteError('R02 등록부의 노선 활성화가 필요합니다.')
        if not str(access_evidence).strip():
            raise RouteError('정류장 접근·정차 가능 및 고정 경로 운행 확인 근거를 입력하세요.')
        vehicle=next((v for v in read_rows(connection,'fixed_vehicles') if v['vehicle_id']==vehicle_id and v['available']),None)
        if not vehicle:
            raise RouteError('이용 가능한 등록 차량이 없습니다.')
        if plan['test_geometry'] and not vehicle['test_only']:
            raise RouteError('시험용 경로에는 시험용 차량·운행편만 등록할 수 있습니다.')
        try:
            values=[float(offsets[k]) for k in plan['order']]
        except (KeyError,ValueError,TypeError):
            raise RouteError('전체 정류장의 출발 후 예정 승차/도착 분 값을 입력하세요.') from None
        if not all(math.isfinite(x) for x in values) or values[0]!=0 or any(b<=a for a,b in zip(values,values[1:])):
            raise RouteError('첫 정류장은 0분, 이후 정류장은 순서대로 증가하는 유한한 값이어야 합니다.')
        if values[-1] < plan['duration_min'] or any(
                values[i+1]-values[i] < float(segment['duration_min']) for i,segment in enumerate(plan['segments'])):
            raise RouteError('등록 시간표가 저장된 도로 모형 이동시간보다 짧습니다. 정차·접근 시간을 포함해 확인하세요.')
        start=departure.astimezone(timezone.utc);end=start+timedelta(minutes=values[-1])
        for old in read_rows(connection,'fixed_runs'):
            if old['vehicle_id']==vehicle_id and start<datetime.fromisoformat(old['end_at']) and datetime.fromisoformat(old['departure'])<end:
                raise RouteError('동일 차량의 등록 운행편 시간이 중복됩니다. 회차 이동시간도 별도로 확보하세요.')
        # Old research/CSV assignments also reserve a vehicle; unknown dates
        # cannot be interpreted as a free operational vehicle.
        for old in service.list_records():
            if old['status']!='예약완료' or old.get('vehicle_id')!=vehicle_id:
                continue
            booking=old.get('booking_snapshot')
            if not booking:
                raise RouteError('날짜 미확인 기존 예약이 배정된 차량입니다. 운영 기록을 확인하세요.')
            if start<datetime.fromisoformat(booking['run_end_at']) and datetime.fromisoformat(booking['departure'])<end:
                raise RouteError('기존 차량 배정 시간과 겹칩니다.')
        row=dict(run_id='RUN:'+uuid4().hex.upper(),route_id=route_id,vehicle_id=vehicle_id,departure=start.isoformat(),end_at=end.isoformat(),
            order=plan['order'],route_signature=plan['signature'],offsets=dict(zip(plan['order'],values)),access_evidence=str(access_evidence).strip(),
            capacity=vehicle['capacity'],test_only=vehicle['test_only'],active=True)
        connection.execute('INSERT INTO fixed_runs VALUES(?,?)',(row['run_id'],json.dumps(row,ensure_ascii=False)))
        return row


def boarding_at(run,stop_id):
    return datetime.fromisoformat(run['departure'])+timedelta(minutes=run['offsets'][stop_id])


def assign(service,connection,state,record,run_id=None,reference_now=None):
    """Called inside the same IMMEDIATE transaction as request creation/retry."""
    plans=route_plans(service.routes.original_loader(),state)
    plan=next(p for p in plans if p['route_id']==record['route_id'])
    record['dispatch_status']='등록된 차량·날짜별 운행편 없음; 배차 검토 필요'
    if not plan['road_complete']:
        record['dispatch_status']='최종 트램까지 순차 도로 경로 미확인; 배차 검토 필요'
        return
    if plan['route_id']=='R02' and not plan['active']:
        record['dispatch_status']='R02 비활성; 배차 검토 필요'
        return
    vehicles={v['vehicle_id']:v for v in read_rows(connection,'fixed_vehicles')}
    runs=[r for r in read_rows(connection,'fixed_runs') if r['route_id']==record['route_id'] and r['active'] and (run_id is None or r['run_id']==run_id)]
    if run_id is not None and not runs:
        raise RouteError('선택한 운행편이 없거나 예약 노선과 다르거나 비활성입니다.')
    current=reference_now or datetime.now(timezone.utc)
    requested=datetime.fromisoformat(record['requested_at'])
    occupied_rows=[json.loads(r[0]) for r in connection.execute('SELECT payload FROM requests')]
    legacy=service._csv_rows()
    cancelled={r[0] for r in connection.execute('SELECT public_id FROM csv_cancellations')}
    from modules.unified_reservations import csv_public_id
    bookings=[b for b in state['bookings'] if b['status']=='reserved']
    bookings += [r['booking_snapshot'] for r in occupied_rows if r['status']=='예약완료' and r.get('booking_snapshot')]
    for run in sorted(runs,key=lambda r:r['departure']):
        vehicle=vehicles.get(run['vehicle_id'])
        if not vehicle or not vehicle['available'] or vehicle['test_only']!=run['test_only']:
            continue
        if plan['test_geometry'] and not run['test_only']:
            continue
        if run['route_signature']!=plan['signature'] or run['order']!=plan['order']:
            record['dispatch_status']='노선 경로가 운행편 등록 당시와 달라 재등록 필요'
            continue
        if datetime.fromisoformat(run['departure'])<=current or boarding_at(run,record['boarding_stop'])!=requested:
            record['dispatch_status']='희망 승차시각과 등록 운행편의 정류장별 예정 시각이 맞지 않음'
            continue
        if record.get('tram_departure') and datetime.fromisoformat(run['end_at'])+timedelta(minutes=float(setting('transfer_buffer')))>datetime.fromisoformat(record['tram_departure']):
            record['dispatch_status']='등록 운행편이 가상 트램 목표 시각을 충족하지 못함'
            continue
        if any(r['status']=='예약완료' and r['vehicle_id']==run['vehicle_id'] and csv_public_id(r,service.legacy_path) not in cancelled for r in legacy):
            record['dispatch_status']='날짜 미확인 기존 예약 차량이어서 가용 여부 확인 필요'
            continue
        occupied=0;conflict=False
        for old in bookings:
            if old['vehicle_id']!=run['vehicle_id']:
                continue
            if old.get('run_id')==run['run_id']:
                occupied+=int(old['passengers'])
            elif datetime.fromisoformat(run['departure'])<datetime.fromisoformat(old['run_end_at']) and datetime.fromisoformat(old['departure'])<datetime.fromisoformat(run['end_at']):
                conflict=True
        if conflict or occupied+record['passengers']>min(vehicle['capacity'],run['capacity']):
            record['dispatch_status']='차량 정원 초과 또는 동일 차량 시간 중복; 배차 검토 필요'
            continue
        booking=dict(reservation_id=record['public_id'],run_id=run['run_id'],route_id=run['route_id'],
            boarding_stop=record['boarding_stop'],destination_stop=record['destination_stop'],vehicle_id=run['vehicle_id'],
            departure=run['departure'],run_end_at=run['end_at'],passengers=record['passengers'],status='reserved',
            test_only=run['test_only'],run_snapshot=copy.deepcopy(run),route_order=plan['order'])
        record.update(status='예약완료',vehicle_id=run['vehicle_id'],run_id=run['run_id'],booking_snapshot=booking,
            simulation_adapter='excluded',research_only=run['test_only'],dispatch_status='테스트 운행편 합승 배정 · 실제 운행 아님' if run['test_only'] else '등록 차량·운행편 배정 · 실제 운행 개시 정보 없음')
        return

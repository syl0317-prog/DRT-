"""Reference operating costs, explicitly including annualization assumptions."""
import json
import pandas as pd
from modules.settings import PROJECT_DIR, setting

def cost_table(vehicles):
    data = json.loads((PROJECT_DIR / 'data/assumptions/drt_cost_scenarios.json').read_text(encoding='utf-8'))
    days = setting('operating_days_per_year')
    fare = data['operation']['fare_adult_won']['value']
    rows = []
    for name, s in data['scenarios'].items():
        annual = s.get('total_yearly_excl_insurance', s.get('annual_cost_per_vehicle_won'))
        if annual is None:
            continue
        # high is a government budget benchmark; insurance inclusion is unknown.
        insurance = '보험료 포함 여부 missing' if name == 'high' else ('보험료 미반영' if s.get('insurance') is None else '보험료 반영')
        for demand in (43, 72):
            annual_total = annual * vehicles
            passengers = vehicles * demand * days
            per_passenger = annual_total/passengers
            rows.append({'시나리오': name, '차량수': vehicles, '월비용_원': annual_total/12, '연비용_원': annual_total,
                '대당하루이용객': demand, '전체하루이용객': vehicles*demand, '이용객당운영비_원': per_passenger,
                '성인요금_원': fare, '요금차감참고_원': per_passenger-fare, '보험료': insurance,
                '상태': s['status'], '출처': s.get('source', 'data/assumptions/drt_cost_scenarios.json: 팀 가정'),
                '비고': f'연 {days}일 가정; 월비용=연비용/12; 환승할인·실제 수입 미반영'})
    return pd.DataFrame(rows)

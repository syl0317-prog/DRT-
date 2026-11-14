"""Read-only file provenance/quality audit. Never exports reservation contents."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'sewook31'))
from modules.system_views import data_inventory


def audit(output):
    rows=data_inventory()
    for row in rows:
        p=ROOT/row['파일']
        row['행/피처 수']='미검사';row['빈 셀 수']='미검사';row['스키마/품질']='형식별 원천 검토 필요'
        if p.stat().st_size > 20_000_000:
            row['스키마/품질']='20MB 초과: 메타데이터만 검사'
            continue
        if p.suffix.lower() in ('.csv','.json','.geojson'):
            row['SHA256']=hashlib.sha256(p.read_bytes()).hexdigest()
        try:
            if p.suffix.lower()=='.csv':
                with p.open(encoding='utf-8-sig',newline='') as handle:
                    reader=csv.DictReader(handle);fields=reader.fieldnames or []
                    n=empty=bad=0
                    for record in reader:
                        n+=1;empty+=sum(v in (None,'','missing') for v in record.values())
                        bad+=int(None in record or any(v is None for v in record.values()))
                row['행/피처 수']=n;row['빈 셀 수']=empty
                row['스키마/품질']=f'열 {len(fields)}개; 열수 불일치 {bad}행; 값의 의미·실측 여부는 별도 검증'
            elif p.suffix.lower() in ('.json','.geojson'):
                value=json.loads(p.read_text(encoding='utf-8-sig'))
                if isinstance(value,dict) and 'features' in value:
                    row['행/피처 수']=len(value['features'])
                    row['스키마/품질']='GeoJSON 구문 정상; 좌표계·위상 별도 검증'
                else:
                    row['행/피처 수']=len(value)
                    row['스키마/품질']='JSON 구문 정상; 모형/실측 분류는 출처 메타데이터 기준'
        except (OSError,ValueError,TypeError,csv.Error) as error:
            row['스키마/품질']=f'검사 실패: {type(error).__name__}'
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with output.open('x',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    print(json.dumps({'files':len(rows),'output':str(output),'created_at_utc':datetime.now(timezone.utc).isoformat()}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    audit(parser.parse_args().output)

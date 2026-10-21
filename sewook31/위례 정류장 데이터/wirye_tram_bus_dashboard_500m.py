"""원본을 보존하는 300m 기본 / 300~500m 보조 분석 대시보드.

streamlit run wirye_tram_bus_dashboard_500m.py
python -B wirye_tram_bus_dashboard_500m.py --verify
API 호출, .env 접근, 데이터 쓰기 없음. --verify만 별도 검증 보고서를 생성한다.
"""
from pathlib import Path
import math
import html
import sys
import json
from datetime import datetime
import pandas as pd

ROOT = Path(__file__).resolve().parent
CORE = '300m 이내(기본)'
OUTER = '300m 초과~500m 이내(보조)'
BLUE = '#1565c0'
ORANGE = '#e87916'


def haversine(a, b, c, d):
    v = math.sin(math.radians(c-a)/2)**2 + math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(math.radians(d-b)/2)**2
    return 12742000*math.asin(math.sqrt(max(0, min(1,v))))


def classify(distance):
    if distance <= 300:
        return CORE
    if distance <= 500:
        return OUTER
    return '500m 초과(표시 제외)'


def read_csv(path):
    return pd.read_csv(path, encoding='utf-8-sig', dtype={'버스정류장ID':str,'버스정류장번호':str}).fillna('')


def normalize(frame, tram, source, recompute=False):
    rows = []
    lookup = tram.set_index('정거장번호')
    for _, r in frame.iterrows():
        try:
            number = int(r['트램정거장번호'])
            if number not in lookup.index:
                continue
            lat, lon = float(r['버스위도']), float(r['버스경도'])
            if not (math.isfinite(lat) and math.isfinite(lon) and 37.4 <= lat <= 37.6 and 127 <= lon <= 127.3):
                raise ValueError('버스 좌표 범위 오류')
            t = lookup.loc[number]
            distance = haversine(float(t['위도']),float(t['경도']),lat,lon) if recompute else float(r['직선거리_m'])
            if not math.isfinite(distance) or distance < 0:
                raise ValueError('거리 오류')
            if distance > 500:
                continue
            ident = str(r['버스정류장ID']).strip()
            if not ident or ident.lower() in ('nan','none'):
                ident = '좌표:{:.7f},{:.7f}'.format(lat,lon)
            rows.append({'트램정거장번호':number,'트램정거장명':t['정거장명'],
                         '버스정류장ID':ident,'버스정류장번호':str(r.get('버스정류장번호','')),
                         '버스정류장명':r['버스정류장명'],'버스위도':lat,'버스경도':lon,
                         '직선거리_m':distance,'거리구간':classify(distance),'출처':source})
        except (KeyError,TypeError,ValueError):
            raise ValueError('정류장 데이터의 번호·좌표·거리 또는 필수 열을 확인해 주세요: '+source)
    return rows


def load_data(root=ROOT):
    tram = read_csv(root/'위례_트램정거장_좌표.csv')
    tram['정거장번호'] = pd.to_numeric(tram['정거장번호'],errors='raise').astype(int)
    tram = tram[tram['정거장번호'].between(105,112)].copy().sort_values('정거장번호')
    if tram['정거장번호'].duplicated().any() or len(tram) != 8:
        raise ValueError('105~112번 트램 좌표가 각각 한 행씩 필요합니다.')
    for col in ('위도','경도'):
        tram[col] = pd.to_numeric(tram[col],errors='raise')
    if not (tram['위도'].between(37.4,37.6).all() and tram['경도'].between(127,127.3).all()):
        raise ValueError('트램 좌표 범위를 확인해 주세요.')
    baseline = read_csv(root/'위례트램_300m_버스정류장_분석.csv')
    # 기본 분석은 기존 저장 거리와 300m 기준을 그대로 유지한다.
    baseline = baseline[pd.to_numeric(baseline['직선거리_m'],errors='raise') <= 300]
    records = normalize(baseline,tram,'위례트램_300m_버스정류장_분석.csv')
    coverage, notes = {}, []
    # 정거장마다 최신 성공 실행만 선택. 최신 실행 실패가 과거 성공을 지우지 않는다.
    for folder in sorted(root.glob('diagnostics_105_106_*'),reverse=True):
        summary_path, detail_path = folder/'정거장별_진단요약.csv', folder/'정류장별_거리진단.csv'
        if not summary_path.exists() or not detail_path.exists():
            continue
        summary, detail = read_csv(summary_path), read_csv(detail_path)
        for _, s in summary.iterrows():
            n = int(s['트램정거장번호'])
            if n in coverage or n not in tram['정거장번호'].values or s['API상태'] != '성공':
                continue
            group = detail[pd.to_numeric(detail['트램정거장번호'],errors='coerce') == n]
            expected, returned = int(s['API전체건수']), int(s['실제반환건수'])
            if len(group) != returned or returned != expected:
                notes.append('{}번 {}: 건수 불일치로 제외'.format(n,folder.name))
                continue
            # 같은 기준 좌표인지 확인 후 원본 API 반환 좌표로 반올림 전 거리를 재계산.
            t = tram[tram['정거장번호']==n].iloc[0]
            if abs(float(s['트램위도'])-t['위도']) > 1e-7 or abs(float(s['트램경도'])-t['경도']) > 1e-7:
                notes.append('{}번 {}: 트램 좌표 불일치로 제외'.format(n,folder.name))
                continue
            source = folder.name+'/정류장별_거리진단.csv'
            records.extend(normalize(group,tram,source,recompute=True))
            coverage[n] = source
    columns = ['트램정거장번호','트램정거장명','버스정류장ID','버스정류장번호','버스정류장명','버스위도','버스경도','직선거리_m','거리구간','출처']
    links = pd.DataFrame(records,columns=columns)
    # 기존 기본 결과를 우선하며 동일 트램·버스정류장 연결은 한 번만 센다.
    links = links.drop_duplicates(['트램정거장번호','버스정류장ID'],keep='first')
    links = links.sort_values(['트램정거장번호','직선거리_m']).reset_index(drop=True)
    return tram, links, coverage, notes


def summarize(tram, links, coverage):
    result = tram[['정거장번호','정거장명']].copy()
    for label in (CORE,OUTER):
        counts = links[links['거리구간']==label].groupby('트램정거장번호').size()
        result[label] = result['정거장번호'].map(counts).fillna(0).astype(float)
    result.loc[~result['정거장번호'].isin(coverage),OUTER] = float('nan')
    result['보조 분석 상태'] = result['정거장번호'].map(lambda n: '수집 완료' if n in coverage else '미수집')
    return result


def unique_stops(links):
    rows = []
    for ident, group in links.groupby('버스정류장ID',sort=False):
        row = group.sort_values('직선거리_m').iloc[0].to_dict()
        row['연결트램수'] = group['트램정거장번호'].nunique()
        row['연결트램'] = ', '.join(str(n) for n in sorted(group['트램정거장번호'].unique()))
        row['표시구간'] = CORE if (group['거리구간']==CORE).any() else OUTER
        rows.append(row)
    return pd.DataFrame(rows,columns=list(links.columns)+['연결트램수','연결트램','표시구간'])


def make_map(tram, links, show300=True, show500=True):
    import folium
    m = folium.Map(location=[tram['위도'].mean(),tram['경도'].mean()],zoom_start=14,tiles='OpenStreetMap')
    circles300 = folium.FeatureGroup(name='기본 반경 300m · 파란 실선')
    circles500 = folium.FeatureGroup(name='보조 반경 500m · 주황 점선')
    stops = folium.FeatureGroup(name='버스정류장 · 고유 ID별 1개 마커')
    for _, t in tram.iterrows():
        center = [t['위도'],t['경도']]
        folium.Marker(center,tooltip='{} {}'.format(t['정거장번호'],t['정거장명']),icon=folium.Icon(color='gray',icon='train',prefix='fa')).add_to(m)
        if show500:
            folium.Circle(center,radius=500,color=ORANGE,weight=2,dash_array='8,6',fill=False,tooltip='보조: 직선거리 500m').add_to(circles500)
        if show300:
            folium.Circle(center,radius=300,color=BLUE,weight=3,fill=True,fill_opacity=0.035,tooltip='기본: 직선거리 300m').add_to(circles300)
    circles500.add_to(m)
    circles300.add_to(m)
    for _, stop in unique_stops(links).iterrows():
        group = links[links['버스정류장ID']==stop['버스정류장ID']]
        body = '<b>'+html.escape(str(stop['버스정류장명']))+'</b><br>ID: '+html.escape(str(stop['버스정류장ID']))
        for _, r in group.iterrows():
            body += '<br>{} {}: {:.1f}m · {}'.format(r['트램정거장번호'],html.escape(str(r['트램정거장명'])),r['직선거리_m'],html.escape(r['거리구간']))
        color = BLUE if stop['표시구간']==CORE else ORANGE
        folium.CircleMarker([stop['버스위도'],stop['버스경도']],radius=7,color=color,fill=True,fill_color=color,fill_opacity=0.9,
                            tooltip='{} · 연결 {}개'.format(stop['버스정류장명'],stop['연결트램수']),popup=folium.Popup(body,max_width=480)).add_to(stops)
    stops.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([[tram['위도'].min()-0.005,tram['경도'].min()-0.007],[tram['위도'].max()+0.005,tram['경도'].max()+0.007]])
    return m


def app():
    import streamlit as st
    from streamlit_folium import st_folium
    st.set_page_config(page_title='위례선 트램·버스 거리 분석',layout='wide')
    st.title('위례선 트램·버스 환승 연계 분석')
    st.info('기본 분석은 300m 이내이며, 300m 초과~500m 이내는 보조 분석입니다. 모두 직선거리이며 실제 보행거리가 아닙니다.')
    st.warning('트램 정거장 좌표는 지도 추정값입니다. 공식 정거장 위치·출입구와 다를 수 있습니다.')
    try:
        tram, links, coverage, notes = load_data()
    except Exception as exc:
        st.error('데이터 읽기 실패: '+str(exc))
        st.stop()
    st.sidebar.header('표시 설정')
    selected = st.sidebar.multiselect('트램 정거장',options=tram['정거장번호'].tolist(),default=tram['정거장번호'].tolist(),
                                     format_func=lambda n: '{} {}'.format(n,tram.loc[tram['정거장번호']==n,'정거장명'].iloc[0]))
    bands = st.sidebar.multiselect('버스 거리 구간',options=[CORE,OUTER],default=[CORE,OUTER])
    show300 = st.sidebar.checkbox('300m 실선 표시',value=True)
    show500 = st.sidebar.checkbox('500m 점선 표시',value=True)
    if not selected:
        st.info('정거장을 하나 이상 선택해 주세요.')
        st.stop()
    visible_tram = tram[tram['정거장번호'].isin(selected)]
    all_links = links[links['트램정거장번호'].isin(selected)]
    visible = all_links[all_links['거리구간'].isin(bands)]
    unique = unique_stops(visible)
    a,b,c,d = st.columns(4)
    a.metric('기본 300m 연결 관계',int((visible['거리구간']==CORE).sum()))
    b.metric('보조 300~500m 연결 관계',int((visible['거리구간']==OUTER).sum()))
    c.metric('표시 고유 버스정류장',len(unique))
    d.metric('추가 연결 관계 수',len(visible)-len(unique))
    st.caption('지표와 지도는 선택한 정거장·거리 구간 기준입니다. 추가 연결 관계 수 = 연결 관계 수 − 고유 정류장 수.')
    st.markdown('🔵 **300m 이내** · 🟠 **300m 초과~500m 이내** · 300m 파란 실선 / 500m 주황 점선')
    st.caption('동일 정류장은 지도에 한 번 표시합니다. 선택 범위에서 300m 이내 연결이 하나라도 있으면 파란색이며, 팝업에서 모든 연결을 확인할 수 있습니다.')
    st_folium(make_map(visible_tram,visible,show300,show500),height=650,width=None,returned_objects=[])
    st.subheader('정거장별 거리 구간 집계')
    st.caption('이 표와 그래프는 선택한 트램 정거장의 두 거리 구간을 항상 비교합니다. 보조 자료가 없는 정거장은 미수집이며 0개가 아닙니다.')
    summary = summarize(visible_tram,all_links,coverage)
    shown = summary.copy()
    shown[CORE] = shown[CORE].map(lambda v: str(int(v)))
    shown[OUTER] = shown[OUTER].map(lambda v: '미수집' if pd.isna(v) else str(int(v)))
    st.dataframe(shown,hide_index=True,width='stretch')
    st.bar_chart(summary.set_index('정거장명')[[CORE,OUTER]])
    st.subheader('여러 트램 정거장과 연결된 버스정류장')
    shared = unique[unique['연결트램수']>1]
    st.write('여러 트램 연결 정류장: {}개 / 고유 정류장: {}개 / 연결 관계: {}건'.format(len(shared),len(unique),len(visible)))
    st.dataframe(shared[['버스정류장ID','버스정류장명','연결트램수','연결트램','표시구간']],hide_index=True,width='stretch')
    st.subheader('트램·버스 연결 상세 및 출처')
    st.dataframe(visible,hide_index=True,width='stretch')
    st.download_button('연결 관계 CSV 다운로드',visible.to_csv(index=False).encode('utf-8-sig'),'위례트램_거리구간별_연결관계.csv','text/csv')
    st.download_button('고유 정류장 CSV 다운로드',unique.to_csv(index=False).encode('utf-8-sig'),'위례트램_고유버스정류장.csv','text/csv')
    with st.expander('데이터 범위·해석 방법'):
        st.write('원본 300m 결과를 유지하고, 정거장별 최신 성공 진단의 실제 반환 정류장만 추가합니다. 다른 트램으로 연결 관계를 추정하거나 API를 호출하지 않습니다.')
        st.write('300m < d ≤ 500m가 보조 구간입니다. 진단 데이터는 현재 트램 좌표와 일치하는지 확인하고 반올림 전 거리로 분류합니다.')
        st.write('동일 트램 번호·버스 ID는 한 연결로 집계합니다. ID가 없으면 좌표를 사용합니다. 미정차 지점도 원본에 포함된 경우 표시되므로 승하차 가능 여부를 별도 확인해야 합니다.')
        st.dataframe(pd.DataFrame([{'정거장번호':n,'성공 진단 출처':src} for n,src in sorted(coverage.items())]),hide_index=True)
        for note in notes:
            st.warning(note)


def verify():
    import hashlib
    sources = [p for p in ROOT.rglob('*') if p.is_file() and p.suffix in ('.csv','.xlsx','.xls','.py') and 'Microsoft' not in p.parts]
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    tram, links, coverage, notes = load_data()
    summary = summarize(tram,links,coverage)
    assert [classify(d) for d in (300,300.000001,500,500.000001)] == [CORE,OUTER,OUTER,'500m 초과(표시 제외)']
    assert not links.duplicated(['트램정거장번호','버스정류장ID']).any()
    assert len(links[links['거리구간']==CORE]) == 35
    for n,expected in ((105,2),(106,6)):
        s = summary[summary['정거장번호']==n].iloc[0]
        assert s[CORE] == 0 and s[OUTER] == expected
    assert summary[summary['정거장번호'].between(107,112)][OUTER].isna().all()
    both = unique_stops(links)
    assert len(links)==43 and len(both)==35
    only105 = unique_stops(links[links['트램정거장번호']==105])
    assert len(only105)==2 and (only105['표시구간']==OUTER).all()
    assert unique_stops(links.iloc[:0]).empty
    assert before == {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {'검증시각':datetime.now().isoformat(),'검증':'통과','기본300m연결':35,'보조연결':8,
              '전체연결':len(links),'고유정류장':len(both),'추가연결':len(links)-len(both),
              '여러트램연결정류장':int((both['연결트램수']>1).sum()),'원본파일해시동일':True,
              '검증항목':['300/500m 경계','105=2·106=6','107~112 보조 미수집','관계 중복 제거','정거장 필터별 마커 색상','빈 데이터','원본 해시'],
              '정거장별집계':json.loads(summary.to_json(orient='records',force_ascii=False))}
    output = ROOT/('dashboard_500m_verification_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
    with output.open('x',encoding='utf-8') as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    print('검증 보고서: '+str(output))


if __name__ == '__main__':
    if '--verify' in sys.argv:
        verify()
    else:
        app()

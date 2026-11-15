"""Compact dispatch panels with operational and research scopes separated."""
import sqlite3
import pandas as pd
import streamlit as st
from modules.session_ui import persistent_ui as ui
from modules.sequential_routes import route_plans


def render_dispatch_board(service,tables_loader,compact=False):
    st.subheader('운행편별 배차 현황')
    try:
        plans=route_plans(service.routes.original_loader(),service.routes.snapshot())
        ops=service.operations()
        a,b=st.columns(2)
        with a:
            scope=ui.selectbox('배차 자료',['운영','연구·시험','전체'],key='fixed_board_scope')
        group={'운영':'operating','연구·시험':'research','전체':'all'}[scope]
        runs=[r for r in ops['runs'] if scope=='전체' or (r['test_only'] if scope=='연구·시험' else not r['test_only'])]
        lookup={r['run_id']:r for r in runs}
        previous=st.session_state.get('fixed_board_run')
        if previous is not None and previous not in lookup:
            st.session_state.pop('fixed_board_run',None)
            st.session_state.setdefault('ui_saved_values',{}).pop('fixed_board_run',None)
        with b:
            run_id=ui.selectbox('운행편',[None]+list(lookup),key='fixed_board_run',format_func=lambda k:'전체 운행편' if k is None else f"{lookup[k]['route_id']} · {lookup[k]['vehicle_id']} · {lookup[k]['departure'][:16]}")
        tables=tables_loader(service,run_id,data_scope=group)
        left,right=st.columns(2)
        left.metric('운영 배차 확정' if scope=='운영' else '저장된 배정',tables['assigned'])
        right.metric('접수·배차 대기',tables['pending'])
        if scope!='운영':st.info('연구·시험 배정은 실제 운영 확정과 구분됩니다.')
        run_tab,stop_tab=st.tabs(['차량·운행편','정류장별 승객'])
        with run_tab:
            if tables['runs']:
                frame=pd.DataFrame(tables['runs'])
                st.dataframe(frame[['노선','차량','출발','정원','탑승예정','배차완료','배차대기','구분','최종목적지']],hide_index=True,width='stretch',height=260)
            else:
                st.info('등록 운행편 없음 · 차량 배정은 검토 필요')
        with stop_tab:
            st.dataframe(pd.DataFrame(tables['stops']),hide_index=True,width='stretch',height=300)
        st.caption('배차 확정은 등록 차량·운행편 배정입니다. 실제 운행 상태는 데이터 없음.')
        with st.expander('경유 순서·집계 기준'):
            for p in plans:
                st.write(p['route_id']+' · '+' → '.join(p['order']))
            st.caption(f"날짜 미기록 {tables['undated']}건 및 규칙 불일치 {tables['invalid']}건은 운행편 인원에서 제외합니다. 취소 시 탑승 예정 인원을 다시 계산합니다.")
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        st.error(f'배차 현황 조회 실패: {error}')

"""Reservation list with immutable source status and explicit operational stages."""
from datetime import datetime
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
import streamlit as st
from modules.session_ui import persistent_ui as ui
from modules.reservation_audit import audit_service,display_rows,ACTIVE
from modules.fixed_dispatch import boarding_at

KST=ZoneInfo('Asia/Seoul')


def show_booking_list(service):
    st.subheader('예약 목록')
    try:
        records=audit_service(service)
        a,b,c=st.columns(3)
        with a:
            category=ui.selectbox('자료 구분',['전체','신규 SQLite','과거 CSV','연구·시험','규칙 불일치'],key='ua_category')
        with b:
            selected=ui.selectbox('예약 상태',['전체','배차 검토 필요','배차 확정','예약완료','예약취소'],key='ua_filter',
                format_func=lambda v:{'배차 검토 필요':'접수·대기','예약완료':'배정 기록 (과거·시험 포함)','예약취소':'예약 취소'}.get(v,v))
        with c:
            selected_route=ui.selectbox('노선',['전체','R01','R02'],key='ua_route_filter')
        filtered=[]
        for r in records:
            if selected_route!='전체' and r['route_id']!=selected_route:continue
            if selected=='배차 확정' and r['display_stage']!='배차 확정':continue
            if selected not in ('전체','배차 확정') and r['status']!=selected:continue
            if category=='규칙 불일치' and r['policy_valid']:continue
            if category=='연구·시험' and r['data_category'] not in ('연구 등록부','시험 운행편','과거 연구 배정'):continue
            if category not in ('전체','규칙 불일치','연구·시험') and r['data_category']!=category:continue
            filtered.append(r)
        invalid=sum(not r['policy_valid'] for r in records)
        if invalid:
            st.warning(f'규칙 불일치 {invalid}건 · 원본 보존 · 자료 구분 필터에서 확인')
        if filtered:
            frame=pd.DataFrame(display_rows(filtered))
            st.dataframe(frame[['노선','승차','하차','인원','표시 상태','자료 구분','예약 ID']],hide_index=True,width='stretch',height=260,
                column_config={'예약 ID':st.column_config.TextColumn(width='small')})
        else:
            st.info('선택 조건에 해당하는 예약이 없습니다.')
        st.caption('접수·대기 → 차량·운행편 검토 → 배차 확정. 과거·연구·시험 배정은 운영 확정과 별개입니다.')
        review,cancel,detail=st.tabs(['배차 재검토','예약 취소','원본 정보'])
        with review:
            pending=[r for r in filtered if r['source']=='unified_sqlite' and r['policy_valid'] and r['status']=='배차 검토 필요']
            if pending:
                dispatch_id=ui.selectbox('재검토할 접수',[r['public_id'] for r in pending],key='ua_dispatch_id')
                request=next(r for r in pending if r['public_id']==dispatch_id)
                st.info(f"대기 사유: {request['review_reason']}")
                choices={r['run_id']:r for r in service.operations()['runs'] if r['route_id']==request['route_id'] and r['active'] and datetime.fromisoformat(r['departure'])>datetime.now(KST)}
                retry_run=ui.selectbox('등록 운행편',[None]+list(choices),key='ua_retry_run',format_func=lambda k:'기존 희망시각에 맞는 운행편 검색' if not k else f"{choices[k]['vehicle_id']} · {boarding_at(choices[k],request['boarding_stop']).astimezone(KST):%m/%d %H:%M}"+(' · 시험' if choices[k]['test_only'] else ''))
                accept_time=ui.checkbox('선택 운행편의 승차시각으로 변경 동의',key='ua_accept_run_time') if retry_run else False
                if st.button('배차 재검토',key='ua_retry_dispatch'):
                    result=service.retry_dispatch(dispatch_id,run_id=retry_run,accept_run_time=accept_time)
                    st.session_state['ua_last_result']=result;st.rerun()
            else:
                st.caption('재검토할 유효한 신규 대기 접수 없음')
        with cancel:
            active=[r for r in filtered if r['status'] in ACTIVE]
            if active:
                selected_id=ui.selectbox('취소할 예약',[r['public_id'] for r in active],key='ua_cancel_id')
                if st.button('선택 예약 취소',key='ua_cancel'):
                    service.cancel(selected_id);st.session_state.pop('ua_last_result',None);st.rerun()
            else:
                st.caption('취소 가능한 예약 없음')
        with detail:
            if filtered:
                chosen=ui.selectbox('원본 확인 예약',[r['public_id'] for r in filtered],key='ua_detail_id')
                row=next(r for r in filtered if r['public_id']==chosen)
                st.dataframe(pd.DataFrame(display_rows([row])).T.astype(str).rename(columns={0:'저장값 / 표시 판정'}),width='stretch')
    except (OSError,ValueError,KeyError,sqlite3.Error) as error:
        st.error(f'예약 조회·처리 실패: {error}')

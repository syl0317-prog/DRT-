"""UI and immutable reservation audit regressions; temporary databases only."""
from datetime import timedelta
import copy,hashlib,json,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'sewook31'),str(ROOT/'sewook31/tests')]
import test_sequential_dispatch as fixture_module
from modules.reservation_audit import audit_records,audit_service,audit_summary
from modules.fixed_dispatch import register_vehicle,register_run,boarding_at
from modules.fixed_dispatch_views import dispatch_tables
from streamlit.testing.v1 import AppTest


class OperationsUITests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture_module.SequentialDispatchTests('test_no_vehicle_and_no_inferred_run')
        self.fx.setUp();self.addCleanup(self.fx.tearDown)
        self.service=self.fx.service;self.store=self.fx.store

    def operational_fixture(self):
        # Operational-category schema is exercised only in the isolated TEST DB.
        register_vehicle(self.service,'UI-OPERATING-FIXTURE',4,'TEST ONLY identity fixture',test_only=False)
        run=register_run(self.service,'R01','UI-OPERATING-FIXTURE',self.fx.future+timedelta(hours=2),
            dict(zip(['D01','D02','D03','D04','T01'],[0,3,6,9,12])),'TEST ONLY access fixture')
        return run,self.fx.reserve(run,'D01','operational-fixture')

    def test_history_test_and_operational_categories_do_not_mix(self):
        historical=self.service.list_records()
        pending=self.service.create('D02','T01',self.fx.future,1,'pending')
        test_run=self.fx.make_run();test_row=self.fx.reserve(test_run,'D03','test-fixture')
        _,operational=self.operational_fixture()
        audited=audit_service(self.service);summary=audit_summary(audited)
        by_id={r['public_id']:r for r in audited}
        self.assertEqual(summary['history'],sum(r['source']=='legacy_csv' for r in historical))
        self.assertEqual(summary['confirmed'],1);self.assertEqual(summary['pending'],1)
        self.assertEqual(summary['operating'],2)
        self.assertEqual(by_id[test_row['public_id']]['display_stage'],'연구·시험 배정')
        self.assertEqual(by_id[operational['public_id']]['display_stage'],'배차 확정')
        self.assertEqual(by_id[pending['public_id']]['display_stage'],'예약 접수 · 배차 대기')

    def test_csv_and_sqlite_invalid_combinations_are_flagged_without_mutation(self):
        _,row=self.operational_fixture()
        with self.service.transaction() as (connection,state,attached):
            broken=dict(row,destination_stop='T02')
            connection.execute('UPDATE requests SET payload=? WHERE public_id=?',(json.dumps(broken,ensure_ascii=False),row['public_id']))
        before=hashlib.sha256(self.fx.db.read_bytes()).hexdigest()
        raw=copy.deepcopy(self.service.list_records())
        audit=audit_service(self.service)
        self.assertEqual(self.service.list_records(),raw)
        self.assertEqual(hashlib.sha256(self.fx.db.read_bytes()).hexdigest(),before)
        bad=next(r for r in audit if r['public_id']==row['public_id'])
        self.assertFalse(bad['policy_valid']);self.assertFalse(bad['operating_record'])
        self.assertEqual(bad['status'],'예약완료')
        self.assertEqual(bad['destination_stop'],'T02')
        self.assertEqual(audit_summary(audit)['confirmed'],0)
        table=dispatch_tables(self.service,data_scope='operating')
        self.assertEqual(table['assigned'],0)
        self.assertTrue(any(not r['policy_valid'] and r['data_category']=='과거 CSV' for r in audit))

    def test_wrong_boarding_route_and_cancelled_invalid_records_stay_visible(self):
        row=self.service.list_records()[0]
        rows=[dict(row,public_id='fixture-a',boarding_stop='V05',destination_stop='T01'),
              dict(row,public_id='fixture-b',destination_stop='T02',status='예약취소')]
        original=copy.deepcopy(rows)
        audit=audit_records(rows,self.store.original_loader(),self.store.snapshot())
        self.assertTrue(all(not r['policy_valid'] for r in audit))
        self.assertEqual(audit[1]['display_stage'],'예약 취소')
        self.assertEqual(rows,original)

    def test_dispatch_scopes_separate_test_and_operational_runs(self):
        run=self.fx.make_run();self.fx.reserve(run,'D01','test')
        self.operational_fixture()
        actual=dispatch_tables(self.service,data_scope='operating')
        research=dispatch_tables(self.service,data_scope='research')
        self.assertEqual(actual['assigned'],1);self.assertEqual(research['assigned'],1)
        self.assertTrue(all(r['구분']=='운영 등록' for r in actual['runs']))
        self.assertTrue(all(r['구분']=='테스트' for r in research['runs']))

    def app(self):
        return AppTest.from_file(str(ROOT/'sewook31/app.py'),default_timeout=60).run()

    def check(self,app):
        self.assertEqual(len(app.exception),0,str(app.exception))
        self.assertEqual(len(app.error),0,str([e.value for e in app.error]))

    def test_dashboard_metrics_warn_about_history_without_claiming_real_dispatch(self):
        app=self.app();self.check(app)
        self.assertTrue(any('규칙 불일치' in w.value for w in app.warning))
        metrics={m.label:m.value for m in app.metric}
        self.assertEqual(metrics['신규 유효 접수'],'0');self.assertEqual(metrics['배차 확정'],'0')
        self.assertEqual(metrics['실제 운행 차량'],'데이터 없음')
        self.assertFalse(any('원본 R02 연구용 등록부 상태'==s.value for s in app.subheader))
        self.operational_fixture();app.run();self.check(app)
        self.assertEqual(next(m.value for m in app.metric if m.label=='배차 확정'),'1')

    def test_list_filters_keep_original_status_and_show_invalid_records(self):
        app=self.app();menus=app.sidebar.radio(key='main_menu').options
        app.sidebar.radio(key='main_menu').set_value(menus[1]).run();self.check(app)
        app.selectbox(key='ua_category').set_value('규칙 불일치').run();self.check(app)
        frames=[d.value for d in app.dataframe if '표시 상태' in d.value.columns]
        self.assertTrue(any(not f.empty and f['표시 상태'].eq('규칙 불일치 · 확인 필요').all() for f in frames))
        self.assertTrue(any('원본 상태' in d.value.index for d in app.dataframe))
        self.assertEqual(self.fx.csv.read_bytes(),self.fx.csv_before)

    def test_system_registry_moved_and_research_vehicles_opt_in(self):
        app=self.app();menus=app.sidebar.radio(key='main_menu').options
        app.sidebar.radio(key='main_menu').set_value(menus[2]).run();self.check(app)
        self.assertNotIn('R02 등록부 및 차량',app.radio(key='operations_section').options)
        app.radio(key='operations_section').set_value('연구·관제 도구').run()
        app.radio(key='research_tool').set_value('관제 모형').run();self.check(app)
        self.assertFalse(app.checkbox(key='live_show_simulated').value)
        app.checkbox(key='live_show_simulated').set_value(True).run();self.check(app)
        app.sidebar.radio(key='main_menu').set_value(menus[4]).run();self.check(app)
        self.assertTrue(any(s.value=='원본 R02 연구용 등록부 상태' for s in app.subheader))

    def test_read_queries_use_read_only_sqlite_connections(self):
        self.service.create('D01','T01',self.fx.future,1,'pending')
        connect=sqlite3.connect
        with patch('sqlite3.connect',wraps=connect) as tracked:
            audit_service(self.service)
        self.assertTrue(tracked.call_args_list)
        self.assertTrue(all('mode=ro' in str(call.args[0]) and call.kwargs.get('uri') is True for call in tracked.call_args_list))

    def test_old_operation_menu_selection_recovers_after_ui_update(self):
        app=self.app();menus=app.sidebar.radio(key='main_menu').options
        app.session_state['operations_section']='R02 등록부 및 차량'
        app.session_state['ui_saved_values']['operations_section']='R02 등록부 및 차량'
        app.sidebar.radio(key='main_menu').set_value(menus[2]).run();self.check(app)
        self.assertEqual(app.radio(key='operations_section').value,'통합 노선 지도')

    def test_switching_dispatch_scope_resets_incompatible_run_selection(self):
        test_run=self.fx.make_run();operational,_=self.operational_fixture()
        app=self.app();menus=app.sidebar.radio(key='main_menu').options
        app.sidebar.radio(key='main_menu').set_value(menus[1]).run();self.check(app)
        app.selectbox(key='fixed_board_run').set_value(operational['run_id']).run()
        app.selectbox(key='fixed_board_scope').set_value('연구·시험').run();self.check(app)
        self.assertIsNone(app.selectbox(key='fixed_board_run').value)
        app.selectbox(key='fixed_board_run').set_value(test_run['run_id']).run();self.check(app)


if __name__=='__main__':unittest.main()

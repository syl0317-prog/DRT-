"""Run booking/route regressions without executing punctuality analysis tests."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'sewook31'),str(ROOT/'sewook31/tests')]
import test_integrated_runtime as existing
import test_sequential_dispatch as sequential
import test_team_runtime as recovery


def suite():
    names=[name for name in unittest.defaultTestLoader.getTestCaseNames(existing.IntegrationTests)
           if name!='test_all_menus_and_booking_auto_destination']
    return unittest.TestSuite([
        unittest.TestSuite(existing.IntegrationTests(name) for name in names),
        unittest.defaultTestLoader.loadTestsFromTestCase(sequential.SequentialDispatchTests),
        recovery.TeamRuntimeTests('test_first_run_and_existing_reservations_are_preserved'),
        recovery.TeamRuntimeTests('test_existing_non_database_files_are_not_opened')])


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(suite())
    raise SystemExit(not result.wasSuccessful())

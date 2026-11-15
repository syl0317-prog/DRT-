"""UI/audit plus existing fixed-route regressions; no punctuality execution."""
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'sewook31'),str(ROOT/'sewook31/tests')]
import verify_sequential_routes
import test_operations_ui

if __name__=='__main__':
    suite=unittest.TestSuite([verify_sequential_routes.suite(),unittest.defaultTestLoader.loadTestsFromTestCase(test_operations_ui.OperationsUITests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())

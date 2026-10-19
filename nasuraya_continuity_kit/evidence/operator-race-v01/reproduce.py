"""Run from repository root with Python 3.11+ and Linux libseccomp.so.2.

No package installation, network, canonical state or persistent jobs.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from nasuraya_continuity_kit.verify_local_job import deny_network
from nasuraya_continuity_kit.test_local_job import LocalJobTests

denied = deny_network()
modules = ['nasuraya_continuity_kit.test_local_job',
           'nasuraya_continuity_kit.test_store', 'continuity.test_gate',
           'project_fund.test_planner']
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromNames(modules))
if not result.wasSuccessful():
    raise SystemExit(1)
distinct = result.testsRun
names = ['test_concurrent_pause_collision_preserved_after_publication_and_reopen',
         'test_concurrent_heartbeat_collision_preserved_without_refund',
         'test_newer_pause_rejects_stale_finish_and_retains_unresolved_claim',
         'test_historical_result_replay_does_not_restore_pre_pause_control']
result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(
    LocalJobTests(name) for _ in range(100) for name in names))
print(json.dumps(dict(distinct_tests=distinct, race_repetitions=100,
    repeated_case_executions=result.testsRun, failures=len(result.failures),
    errors=len(result.errors), skips=len(result.skipped), seed=None,
    network_syscalls_denied=denied)))
if not result.wasSuccessful():
    raise SystemExit(1)

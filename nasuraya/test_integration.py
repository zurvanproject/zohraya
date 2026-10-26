import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from .catalog import ROOT, CAPABILITIES, validate
from .__main__ import invoke, environment
from .demo import run


class IntegrationTests(unittest.TestCase):
    def test_dialogue_memory_forecast_and_consolidation_survive_cold_processes(self):
        from .continuity_demo import run as continuity
        with tempfile.TemporaryDirectory() as directory:
            report = continuity(Path(directory)/'demo')
        self.assertEqual(report['native_cycles'], 2)
        self.assertEqual(report['remaining_budget'], 0)
        self.assertEqual(report['episode_count'], 2)
        self.assertEqual(report['cold_replay_cycles'], 0)
        self.assertTrue(report['cold_replay_state_equal'])
        self.assertEqual(report['forecast_methods'], ['persistence_fallback', 'nearest_episode'])
        self.assertEqual(report['external_api_calls'], 0)
        self.assertFalse(report['numeric_gate_eligible'])

    def test_catalog_has_existing_entrypoints_without_initializing_any_state(self):
        self.assertEqual(len(validate()), len(CAPABILITIES))
        for key in ('body','dialogue','articulated','genome','self-model','self-observe',
                    'research-host','research-day','guard','fund'):
            self.assertIn(key,CAPABILITIES)

    def test_dispatch_does_not_use_shell_or_reinterpret_arguments(self):
        with patch('nasuraya.__main__.subprocess.run') as launch:
            invoke('genome', ['--verify','a file; echo forbidden'])
        args,kwargs = launch.call_args
        self.assertEqual(args[0][-1],'a file; echo forbidden')
        self.assertNotIn('shell',kwargs)
        with self.assertRaises(ValueError):invoke('unregistered',[])

    def test_native_cli_retains_commands_from_all_merged_lineages(self):
        result = invoke('body',['--help'],capture=True)
        self.assertEqual(result.returncode,0,result.stderr)
        for key in ('maintain','adaptive','wake','sleep-integration-test',
                    'configure-metacognition','configure-language-advisor'):
            self.assertIn(key,result.stdout)

    def test_stdlib_catalog_works_without_optional_modules(self):
        result = subprocess.run([sys.executable,'-S','-m','nasuraya','catalog'],
                                cwd=ROOT,capture_output=True,text=True,check=True)
        self.assertEqual(len(json.loads(result.stdout)['capabilities']),len(CAPABILITIES))

    def test_genome_dialogue_affect_body_and_cold_replay_share_one_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            report=run(Path(directory)/'demo')
        self.assertEqual(report['executed_cycles'],1)
        self.assertEqual(report['replay_cycles'],0)
        self.assertTrue(report['state_equal_across_cold_replay'])
        self.assertEqual(report['external_api_calls'],0)
        self.assertFalse(report['genome_applied_to_body'])
        self.assertEqual(report['self_observation_cycles'], 0)
        self.assertIsNone(report['self_model_integrity'])
        self.assertEqual(len(report['self_observation_checkpoint_sha256']), 64)


if __name__=='__main__':unittest.main()

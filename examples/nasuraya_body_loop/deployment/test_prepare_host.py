import tempfile
from pathlib import Path
import unittest
from .prepare_host import prepare

class HostPreparationTests(unittest.TestCase):
    def test_units_bind_one_literal_saved_wakeup_without_authorization(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'units'
            manifest=prepare(out,repo='/opt/nasuraya',session='/srv/nasuraya/state.sqlite',wake_id='approved',user='runner')
            text=(out/'nasuraya-wake.service').read_text()
            self.assertIn('User=runner',text)
            self.assertIn('ReadWritePaths=/srv/nasuraya',text)
            self.assertIn('--wake-id approved --allow-live-wakeup',text)
            command=next(line for line in text.splitlines() if line.startswith('ExecStart='))
            self.assertNotIn('authorize-continuation',command)
            self.assertIn('examples.nasuraya_body_loop wake ',command)
            self.assertFalse(manifest['installed'])
            self.assertFalse(manifest['can_refill_budget'])
            self.assertIn('Persistent=true',(out/'nasuraya-wake.timer').read_text())
    def test_path_and_unit_injection_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            for value in ('relative','/opt/path%H','/opt/path\nExecStart=bad','/opt/../else'):
                with self.subTest(value=value),self.assertRaises(ValueError):
                    prepare(Path(t)/'units',repo=value,session='/srv/state.sqlite',wake_id='approved',user='runner')

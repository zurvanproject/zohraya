import unittest
from .dream_ten import Step, dream

class DreamTenTests(unittest.TestCase):
    def test_no_improvement_rejected(self):
        a=[Step(1,.04,2,True)]*10
        r=dream(a,lambda scale,split:a,lambda scale,split:a)
        self.assertFalse(r["accepted"])
        self.assertEqual(r["test_relative_improvement"],0)
    def test_unsafe_winner_rejected(self):
        a=[Step(1,.04,2,True)]*10
        def run(scale,split):
            return [Step(.3,.01,2,False)]*10 if scale==.25 else a
        r=dream(a,run,run)
        self.assertFalse(r["accepted"])
    def test_input_validation(self):
        with self.assertRaises(ValueError): Step(1,float('nan'),0,True)

if __name__=="__main__":
    unittest.main()

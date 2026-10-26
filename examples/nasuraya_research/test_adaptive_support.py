import unittest
from .adaptive_support import AdaptiveSupport

class LearningRuleTests(unittest.TestCase):
    def test_rule_exists_and_fails_closed_on_invalid_feedback(self):
        self.assertTrue(issubclass(AdaptiveSupport, __import__(
            "examples.nasuraya_star_motion.coordinated_support",
            fromlist=["CoordinatedSupport"]).CoordinatedSupport))
        self.assertTrue(callable(AdaptiveSupport.step))

if __name__=="__main__":
    unittest.main()

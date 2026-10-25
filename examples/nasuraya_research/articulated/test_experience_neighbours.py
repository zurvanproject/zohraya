import unittest
from .experience_neighbours import recommend,choose_settings


def memory():
    return [dict(case=dict(id=str(i),friction=.5+i*.01,stride=.06,push=0.),
                 candidate_eligible=True,reduction=.3) for i in range(3)]


class NeighbourTests(unittest.TestCase):
    def test_failed_left_out_candidate_cannot_pass_cross_validation(self):
        rows=memory();rows[0]['candidate_eligible']=False
        best,scores=choose_settings(rows,[[2,.5,.1]])
        self.assertIsNone(best)
        self.assertFalse(scores[0]['all_selected_candidates_eligible'])

    def test_future_push_is_not_a_policy_input(self):
        rows=memory()
        for push in (-100.,0.,100.):
            self.assertEqual(recommend(rows,dict(friction=.51,stride=.06,push=push),[2,.5,.1]),.006)

    def test_conflicting_or_distant_experience_keeps_baseline(self):
        rows=memory();rows[1]['reduction']=-.1
        self.assertEqual(recommend(rows,dict(friction=.51,stride=.06),[2,.5,.1]),0.)
        self.assertEqual(recommend(memory(),dict(friction=1.5,stride=.06),[2,.5,.1]),0.)


if __name__=='__main__':unittest.main()

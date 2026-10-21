"""Small regression checks for source classification and atomic motion refusal."""
from copy import deepcopy
import unittest
from .audit import geometry,trial,PostureLoop,GaitEnvironment,Inputs,VISUAL_REVISION


class AuditTests(unittest.TestCase):
    def test_loaded_patch_area_is_not_the_external_design_target(self):
        g=geometry()
        self.assertAlmostEqual(g['loaded_contact_area_each_cm2'],392.665152498,places=5)
        self.assertEqual(g['foot_external_design_cm']['contact_area_each_cm2'],450)
        self.assertFalse(g['loaded_area_equals_external_target'])

    def test_geometry_is_a_parameter_not_a_biological_measurement(self):
        g=geometry()
        self.assertEqual(g['height_excluding_horns_cm'],250)
        self.assertEqual(g['mass_kg'],195)
        self.assertIsNone(g['separate_horn_mass_kg'])
        self.assertIsNone(g['actual_muscle_volume_cm3'])
        self.assertFalse(g['collision_mesh_available'])
        self.assertAlmostEqual(sum(g['leg_segment_fractions']),1.)

    def test_paired_cosmetic_revision_does_not_advance_the_source(self):
        source=PostureLoop();before=source.checkpoint()
        case=dict(name='short_stand',segments=[['stand',.2]])
        a=trial(source,case);b=trial(source,case)
        self.assertEqual(a['trajectory_sha256'],b['trajectory_sha256'])
        self.assertEqual(source.checkpoint(),before)
        self.assertFalse(VISUAL_REVISION['native_geometry_changed'])

    def test_unsupported_turn_squat_and_stair_leave_state_unchanged(self):
        source=PostureLoop();before=source.checkpoint()
        for command in ('turn','squat','stair'):
            with self.assertRaises(ValueError):source.step(GaitEnvironment(command=command,body=Inputs(dt_s=.1)))
            self.assertEqual(before,source.checkpoint())

    def test_zero_friction_failure_is_retained(self):
        source=PostureLoop()
        result=trial(source,dict(name='zero',segments=[['walk',1.0]],friction=0.))
        self.assertFalse(result['summary']['valid_throughout'])
        self.assertEqual(result['summary']['failure'],'friction_limit_exceeded')


if __name__=='__main__':unittest.main()

import unittest
from evaluation.rewrite_eval import evaluate

class RewriteEvaluationTests(unittest.TestCase):
    def test_ungraded_cases_are_not_counted_as_success(self):
        report=evaluate([{'id':'a','original':'fix','improved':'fix login','judgments':None}])
        self.assertEqual(report['graded'],0)
        self.assertIsNone(report['intent_preserved_rate'])
        self.assertIsNone(report['task_success_improved'])
    def test_paired_outcomes_and_unsupported_requirements(self):
        report=evaluate([{'id':'a','original':'fix','improved':'fix login','judgments':{'intent_preserved':True,'constraints_preserved':False,'unsupported_requirements':2,'task_success_original':False,'task_success_improved':True}}])
        self.assertEqual(report['unsupported_requirements'],2)
        self.assertEqual(report['paired_task_outcomes'],1)
        self.assertEqual(report['task_success_original'],0)
        self.assertEqual(report['task_success_improved'],1)
    def test_rejects_invalid_grades(self):
        with self.assertRaises(ValueError):evaluate([{'id':'a','original':'x','improved':'y','judgments':{'intent_preserved':'yes'}}])

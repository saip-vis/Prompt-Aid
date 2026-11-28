"""Aggregate human-labeled paired prompt reviews without inventing AI grades.

Each JSON case needs id, original, improved, and judgments containing boolean
intent_preserved/constraints_preserved, a non-negative unsupported_requirements
count, and optional boolean task_success_original/task_success_improved. Null
judgments are ungraded. The report does not establish semantic correctness.
"""
import argparse
import json
from pathlib import Path
import statistics


def evaluate(cases):
    if not isinstance(cases, list) or not cases:
        raise ValueError('Provide a non-empty array of review cases.')
    graded=[];ids=set()
    for case in cases:
        if not isinstance(case,dict) or not all(isinstance(case.get(k),str) and case[k].strip() for k in ('id','original','improved')):
            raise ValueError('Each case needs an id, original and improved text.')
        if case['id'] in ids:
            raise ValueError('Case ids must be unique.')
        ids.add(case['id'])
        label=case.get('judgments')
        if label is None: continue
        if not isinstance(label,dict) or any(type(label.get(k)) is not bool for k in ('intent_preserved','constraints_preserved')):
            raise ValueError('Intent and constraint labels must be booleans.')
        if type(label.get('unsupported_requirements')) is not int or label['unsupported_requirements']<0:
            raise ValueError('Unsupported requirement count must be a non-negative integer.')
        for key in ('task_success_original','task_success_improved'):
            if label.get(key) is not None and type(label[key]) is not bool:
                raise ValueError('Task outcomes must be booleans or null.')
        graded.append(label)
    paired=[g for g in graded if g.get('task_success_original') is not None and g.get('task_success_improved') is not None]
    return {'cases':len(cases),'graded':len(graded),'ungraded':len(cases)-len(graded),
            'intent_preserved_rate':statistics.mean(g['intent_preserved'] for g in graded) if graded else None,
            'constraints_preserved_rate':statistics.mean(g['constraints_preserved'] for g in graded) if graded else None,
            'unsupported_requirements':sum(g['unsupported_requirements'] for g in graded),
            'paired_task_outcomes':len(paired),
            'task_success_original':statistics.mean(g['task_success_original'] for g in paired) if paired else None,
            'task_success_improved':statistics.mean(g['task_success_improved'] for g in paired) if paired else None,
            'limitations':['Judgments are supplied by human evaluators, not inferred by this script.',
                           'Paired tasks must use the same model, tools, task tests and comparable execution budgets.',
                           'Use held-out repositories; record evaluator identity and disagreements separately.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('cases',type=Path);args=p.parse_args()
    print(json.dumps(evaluate(json.loads(args.cases.read_text())),indent=2))
if __name__=='__main__':main()

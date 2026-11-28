"""Summaries of actual recorded evidence; never synthesize model runs or grades."""
def summary(snapshot):
    checks=snapshot.get('checks',[]);cases=[case for check in checks for case in check.get('cases',[])]
    return {'label':snapshot['label'],'turn':snapshot.get('turn',0),'kind':snapshot['kind'],
            'elapsed_ms':snapshot.get('elapsed_ms'),'worker_ms':snapshot.get('worker_ms'),
            'usage':snapshot.get('usage',{}),'checks_passed':sum(c['passed'] for c in checks),'checks_total':len(checks),
            'cases_passed':sum(c['passed'] for c in cases),'cases_total':len(cases),
            'checks':checks,'output':snapshot.get('output'),'created_at':snapshot.get('created_at')}


def compare(job,baseline_job=None):
    attempts=job['payload'].get('attempts',[])
    if not attempts:return {'mode':'unavailable','comparable':False,'notes':['This historical run has no recorded comparison snapshots.'],'baseline':None,'result':None,'replay':[]}
    result=attempts[-1];notes=[]
    if baseline_job:
        if job['root']!=baseline_job['root']:raise ValueError('Comparison must stay within one project.')
        prior=baseline_job['payload'].get('attempts',[])
        if not prior:raise ValueError('The selected baseline has no recorded evidence.')
        baseline=prior[-1];mode='cross_run'
        same=bool(job['payload'].get('base_commit')) and job['payload'].get('base_commit')==baseline_job['payload'].get('base_commit')
        for key in ['goal','checks','acceptance_criteria','max_turns','max_seconds']:
            same=same and job['spec'].get(key)==baseline_job['spec'].get(key)
        same=same and job['payload'].get('verification_pack',{}).get('sha256')==baseline_job['payload'].get('verification_pack',{}).get('sha256')
        notes.append('Cross-run results are observational. Worker model/settings are not pinned, so this is not a controlled model-quality comparison.')
        if not same:notes.append('Starting code, checks, goal or budgets differ. Do not attribute the difference to Prompt Aid.')
    else:
        baseline=next((a for a in attempts if a['kind']=='baseline'),None);mode='within_run';same=baseline is not None
        notes.append('Starting code versus recorded worktree results on the same frozen examples. This does not compare Prompt Aid against an unaided LLM.')
    notes.append('Synthetic fixture results describe these cases only. Replay shows saved evidence and does not run a model. Token counts are not a dollar-cost estimate.')
    if result['kind']=='baseline' and job['payload'].get('turn',0)>0:notes.append('No worker-result snapshot was saved. This view shows starting-code evidence only, not completed worker verification.')
    if job['payload'].get('attempts_truncated'):notes.append('Older intermediate snapshots were omitted to keep this history bounded.')
    return {'mode':mode,'comparable':bool(same),'notes':notes,'baseline':summary(baseline) if baseline else None,'result':summary(result),
            'replay':[summary(item) for item in attempts]}

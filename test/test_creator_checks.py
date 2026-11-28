import copy
import json
import os
import re
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from test_builds import BuildFixture,wait
from backend.creator_checks import PACK,CRITERIA,checks,freeze,load,validate,demo_spec
from backend.build_comparison import compare
from backend.build_api import StartBuild


def correct_output(pack):
    output=[]
    for case in pack['cases']:
        item={'id':case['id'],**copy.deepcopy(case['expected'])};body=case['body'];evidence={}
        for field in ['budget','currency','deadline']:
            value=item[field]
            if value is None:evidence[field]=None
            elif field=='budget':
                evidence[field]=next(match[0] for match in re.finditer(r'(?:USD|EUR|GBP|CAD|\$)\s*([\d,]+)',body) if int(match[1].replace(',',''))==value)
            else:evidence[field]=str(value)
        evidence['deliverables']=list(item['deliverables']);item['evidence']=evidence;output.append(item)
    return output


class CreatorChecksTests(BuildFixture):
    def setUp(self):
        super().setUp();self.pack=json.loads(PACK.read_text())

    def test_protected_verdicts_find_inventions_conflicts_and_missing_evidence(self):
        output=correct_output(self.pack)
        for rule in ['budget','currency','deadline','source_evidence']:
            self.assertTrue(all(c['passed'] for c in validate(self.pack,output,rule)))
        output[1]['budget']=2500
        self.assertFalse(validate(self.pack,output,'budget')[1]['passed'])
        output[3]['currency']='USD'
        self.assertFalse(validate(self.pack,output,'currency')[3]['passed'])
        output[4]['deadline']='2026-12-10'
        self.assertFalse(validate(self.pack,output,'deadline')[4]['passed'])
        output[0]['evidence']['budget']='not in the email'
        self.assertFalse(validate(self.pack,output,'source_evidence')[0]['passed'])
        self.assertFalse(validate(self.pack,[output[0]]*12,'budget')[0]['passed'])
        self.assertFalse(validate(self.pack,{},'budget')[0]['passed'])

    def test_frozen_inputs_are_independent_of_project_edits_and_detect_tampering(self):
        metadata=freeze(self.directory)
        (self.root/'inbox.json').write_text('changed by worker')
        pack,inputs=load(self.directory,metadata)
        self.assertEqual(len(pack['cases']),12);self.assertNotIn('changed by worker',inputs.read_text())
        os.chmod(inputs,0o600);inputs.write_text('[]')
        with self.assertRaises(ValueError):load(self.directory,metadata)

    def test_check_links_are_validated_before_execution(self):
        spec=demo_spec(self.root);spec['approved']=True
        value=StartBuild.model_validate(spec)
        self.assertEqual(value.checks[0].criterion_indices,[0])
        spec['acceptance_criteria']=['Only one criterion']
        with self.assertRaises(ValueError):StartBuild.model_validate(spec)

    def test_real_check_path_caches_extractor_and_links_source_assertions(self):
        (self.root/'extract_offers.py').write_text('placeholder')
        # Commit a clean starting fixture; only the worker may change its worktree.
        import subprocess
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','extractor fixture'],check=True)
        responses=[]
        bad=correct_output(self.pack);bad[1]['budget']=2500
        good=correct_output(self.pack)
        def worker(prompt,root,turn,stop):
            self.assertIn('baseline_failures',prompt);(root/'extract_offers.py').write_text('fixed candidate')
            return {'status':'completed','summary':'Fixed extractor.','question':''}
        controller=self.controller(worker)
        def process(*args,**kwargs):
            output=bad if len(responses)==0 else good;responses.append(1);return 0,json.dumps(output)
        spec=demo_spec(self.root);spec.update(approved=True,max_seconds=30,max_turns=1)
        with patch.object(controller,'_process',side_effect=process):
            job=controller.start(StartBuild.model_validate(spec).model_dump());final=wait(controller,job['id'])
        self.assertEqual(len(responses),2) # Once per phase, not once per rule.
        self.assertEqual(final['state'],'needs_review')
        self.assertTrue(all(c['automated_status']=='passed' for c in final['payload']['criteria']))
        self.assertTrue(all(c['status']=='pending' for c in final['payload']['criteria']))
        comparison=compare(final)
        self.assertLess(comparison['baseline']['cases_passed'],comparison['result']['cases_passed'])
        self.assertEqual(comparison['result']['cases_total'],48)
        self.assertEqual(len(comparison['replay']),2)
        self.assertIsNotNone(comparison['baseline']['output'])
        self.assertNotIn('verification/inputs.json',controller._profile(Path(final['payload']['worktree']),self.root,Path(final['payload']['worktree']).parent/'tmp')[1])

    def test_comparison_stays_in_project_and_does_not_invent_history(self):
        empty={'root':'a','payload':{},'spec':{}}
        self.assertFalse(compare(empty)['comparable']);self.assertEqual(compare(empty)['replay'],[])
        snapshot={'kind':'baseline','label':'Actual measured code','checks':[]}
        job={'root':'a','spec':{},'payload':{'attempts':[snapshot]}}
        other={'root':'b','spec':{},'payload':{'attempts':[snapshot]}}
        with self.assertRaises(ValueError):compare(job,other)
        self.assertTrue(compare(job)['comparable'])
        cross=compare(job,job)
        self.assertTrue(any('not pinned' in note for note in cross['notes']))

    def test_worker_usage_event_preserves_reported_and_cached_token_counts(self):
        controller=self.controller(lambda *_:None);job=self.store.create(self.spec())
        controller._record_worker(job['id'],{'type':'turn.completed','usage':{'input_tokens':120,'output_tokens':20,'cached_input_tokens':80}})
        controller._record_worker(job['id'],{'type':'item.completed','item':{'type':'agent_message','text':'Finished'}})
        self.assertEqual(self.store.get(job['id'])['payload']['usage'],{'input_tokens':120,'output_tokens':20,'cached_input_tokens':80})

    def test_authenticated_comparison_endpoint_and_unknown_history(self):
        from backend.app import create_app
        from fastapi.testclient import TestClient
        controller=self.controller(lambda *_:None);job=self.store.create(self.spec())
        with TestClient(create_app(self.workspace,'x'*40,controller),base_url='http://127.0.0.1') as client:
            url='/builds/'+job['id']+'/comparison'
            self.assertEqual(client.get(url).status_code,401)
            response=client.get(url,headers={'Authorization':'Bearer '+'x'*40})
            self.assertEqual(response.json()['mode'],'unavailable')

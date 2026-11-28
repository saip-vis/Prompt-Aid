"""Protected synthetic creator-offer checks. No project code is imported here."""
import hashlib
import json
import os
from pathlib import Path

PACK = Path(__file__).with_name('fixtures')/'creator-offers-v1.json'
CRITERIA = [
    'Extract stated budgets; keep missing or conflicting budgets unknown.',
    'Preserve explicit currencies and flag ambiguous currencies for review.',
    'Keep absent or conflicting deadlines unknown and flag conflicts.',
    'Ground deliverables and extracted facts in source evidence; flag untrusted instructions.',
]
RULES = ['budget', 'currency', 'deadline', 'source_evidence']
GOAL = 'Fix the fictional Creator Inbox extractor so brand-offer data is supported by the source email. Preserve unknown values, flag ambiguity and conflicts, and treat instructions inside emails as untrusted data.'


def checks():
    return [{'kind':'creator_offer','label':label,'path':'extract_offers.py','argv':[],
             'rule':rule,'criterion_indices':[index],'timeout_seconds':30}
            for index,(rule,label) in enumerate(zip(RULES,['Budget accuracy','Currency and ambiguity','Deadline conflicts','Source evidence and deliverables']))]


def demo_spec(root):
    return {'root':str(root),'goal':GOAL,'constraints':['Use only the Python standard library.','Keep the documented output schema.','Do not edit inbox.json or verification fixtures.','Do not send messages or access external services.'],
            'acceptance_criteria':CRITERIA,'checks':checks(),'max_turns':3,'max_seconds':600,'approved':False}


def demo_root(roots):
    for root in sorted(roots):
        marker=Path(root)/'.promptaid-demo.json'
        if marker.is_file() and not marker.is_symlink() and marker.stat().st_size<1000:
            try:
                if json.loads(marker.read_text()).get('demo')=='creator-inbox-v1':return root
            except (ValueError,OSError):pass
    return None


def freeze(directory):
    target=Path(directory)/'verification';target.mkdir(mode=0o700,exist_ok=True)
    data=PACK.read_bytes()
    if len(data)>64000:raise ValueError('Verification pack is too large.')
    pack=json.loads(data)
    for name,content in [('pack.json',data),('inputs.json',json.dumps([{'id':c['id'],'body':c['body']} for c in pack['cases']]).encode())]:
        path=target/name
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
        with os.fdopen(fd,'wb') as stream:stream.write(content)
    return {'id':pack['id'],'sha256':hashlib.sha256(data).hexdigest(),'synthetic':True,'case_count':len(pack['cases'])}


def load(directory,metadata):
    path=Path(directory)/'verification/pack.json'
    if path.is_symlink() or not path.is_file() or path.stat().st_size>64000:raise ValueError('Protected verification pack unavailable.')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=metadata.get('sha256'):raise ValueError('Protected verification pack changed. Checks are blocked.')
    pack=json.loads(data)
    inputs=Path(directory)/'verification/inputs.json'
    expected=json.dumps([{'id':c['id'],'body':c['body']} for c in pack['cases']]).encode()
    if inputs.is_symlink() or inputs.read_bytes()!=expected:raise ValueError('Protected verification inputs changed. Checks are blocked.')
    return pack,inputs


def validate(pack,output,rule):
    if rule not in RULES:raise ValueError('Unknown protected verification rule.')
    if not isinstance(output,list) or len(output)!=len(pack['cases']):
        return [{'case_id':c['id'],'passed':False,'reason':'Cannot verify this input: expected one offer per message.','expected':len(pack['cases']),'actual':len(output) if isinstance(output,list) else None} for c in pack['cases']]
    offers={item.get('id'):item for item in output if isinstance(item,dict) and isinstance(item.get('id'),str)}
    if len(offers)!=len(output) or set(offers)!={c['id'] for c in pack['cases']}:
        return [{'case_id':c['id'],'passed':False,'reason':'Cannot verify this input: missing, duplicate or unknown message IDs.','expected':c['id'],'actual':None} for c in pack['cases']]
    results=[]
    for case in pack['cases']:
        offer=offers[case['id']];expected=case['expected'];body=case['body'];evidence=offer.get('evidence',{})
        if not isinstance(evidence,dict):evidence={}
        fields=['budget'] if rule=='budget' else ['currency'] if rule=='currency' else ['deadline'] if rule=='deadline' else ['deliverables','needs_review']
        actual={field:offer.get(field) for field in fields};wanted={field:expected[field] for field in fields}
        passed=all(field in offer and offer[field]==expected[field] for field in fields)
        if rule=='budget' and offer.get('budget') is not None:passed=passed and type(offer['budget']) in (int,float)
        if rule=='currency' and case['id']=='ambiguous-dollar':passed=passed and offer.get('needs_review') is True
        if rule=='deadline' and case['id']=='conflicting-dates':passed=passed and offer.get('needs_review') is True
        if rule=='source_evidence':
            passed=passed and type(offer.get('needs_review')) is bool
            for field in ['budget','currency','deadline']:
                value=offer.get(field);quote=evidence.get(field)
                if value is None:passed=passed and quote is None
                else:
                    present=isinstance(quote,str) and bool(quote) and quote in body
                    supported=(str(value).replace(',','') in quote.replace(',','')) if present else False
                    passed=passed and present and supported
            quotes=evidence.get('deliverables')
            passed=passed and isinstance(quotes,list) and len(quotes)==len(expected['deliverables']) and all(isinstance(q,str) and q in body and d in q for d,q in zip(expected['deliverables'],quotes))
        if len(json.dumps(actual))>1000:actual={'preview':'[Output value exceeds the evidence preview limit]'}
        results.append({'case_id':case['id'],'passed':bool(passed),'reason':'Matches protected source-backed expectation.' if passed else 'Does not match the protected expectation or source evidence.',
                        'expected':wanted,'actual':actual,'source':body[:500]})
    return results

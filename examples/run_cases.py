"""Run actual CLI acceptance cases and verify candidate/check/source alignment."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

CASES=['normal','missing','no_materials','tool_failure','overlong','too_short',
       'changed_source','empty_results','rule_repair','shorter_target','transient_failure']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['mock','live'],required=True)
    parser.add_argument('--prefix')
    parser.add_argument('--cases',nargs='+',choices=CASES,default=CASES)
    args=parser.parse_args()
    prefix=args.prefix or args.mode
    if not prefix.replace('_','').replace('-','').isalnum(): parser.error('Invalid prefix')
    summary={'mode':args.mode,'cases':[]}
    started=time.perf_counter()
    for name in args.cases:
        source='normal' if name=='transient_failure' else name
        material_file='examples/fixtures/changed.json' if name=='changed_source' else 'examples/fixtures/empty.json' if name=='empty_results' else 'data/materials.json'
        stem=prefix+'_'+name
        command=[sys.executable,'-m','src.main','--mode',args.mode,'--input',f'examples/inputs/{source}.json',
                 '--materials',material_file,'--trace',f'examples/traces/{stem}.json','--output',f'examples/outputs/{stem}.json']
        if name in ('tool_failure','transient_failure'):
            command+=['--inject-failure','estimate_duration','--failure-mode','once' if name=='transient_failure' else 'always']
        before=time.perf_counter()
        run=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=900)
        if not run.stdout: raise RuntimeError(run.stderr)
        result=json.loads(run.stdout)
        trace=json.loads(Path(f'examples/traces/{stem}.json').read_text(encoding='utf-8'))
        expected='needs_information' if name=='missing' else 'needs_materials' if name in ('no_materials','empty_results') else 'tool_failed' if name=='tool_failure' else 'cannot_satisfy' if name=='too_short' else 'completed'
        checks={'status':result['status']==expected,'result_matches_trace':trace['result']==result,
                'not_published':result['published'] is False,'exit_code':run.returncode==(1 if expected=='tool_failed' else 0)}
        histories=result.get('draft_history',[])
        if expected=='completed':
            duration=result.get('duration_check') or {};rules=result.get('rule_check') or {}
            checks['both_checks_passed']=bool(duration.get('passed') and rules.get('passed'))
            checks['within_target']=result.get('estimated_total_seconds',10000)<=result.get('target_seconds',0)
            checks['same_draft_id']=duration.get('draft_id')==rules.get('draft_id')
            checks['scene_total']=sum(s['estimated_seconds'] for s in result['script']['scenes'])+duration['transition_seconds']==result['estimated_total_seconds']
            facts={(m['id'],f['id']):(m['version_date'],f['text']) for m in json.loads(Path(material_file).read_text(encoding='utf-8')) for f in m['facts']}
            checks['sources_match']=all(facts.get((c['source_id'],c['fact_id']))==(c['version_date'],c['quote']) and hashlib.sha256(c['quote'].encode()).hexdigest()==c['content_sha256'] for c in result['source_citations'])
            checks['scene_source_alignment']=all(s['subtitle']==s['source_citation']['quote'] and s['source_id']==s['source_citation']['source_id'] for s in result['script']['scenes'])
        else:
            checks['no_false_approval']=result.get('script') is None and result['approved'] is False
        if name in ('overlong','shorter_target'):
            estimates=[h['duration_check'] for h in histories if h['duration_check']]
            checks['actual_38s_initial']=bool(estimates) and estimates[0]['estimated_total_seconds']==38
            checks['revised_and_rechecked']=len(estimates)>=2 and not estimates[0]['passed'] and estimates[-1]['passed'] and estimates[0]['draft_id']!=estimates[-1]['draft_id']
        if name=='rule_repair':
            checks['rejected_unsupported_claim']=bool(histories and histories[0]['rule_check'] and not histories[0]['rule_check']['passed'])
            checks['no_80_percent_claim']='80%' not in json.dumps(result.get('script'),ensure_ascii=False)
        if name in ('tool_failure','transient_failure'): checks['actual_error']=bool(result.get('tool_errors'))
        if name=='missing': checks['no_model']=not trace['steps'] and trace['model']=='not_called'
        else: checks['actual_loop']=any(s['action'] not in ('model_error','finalize_script') and s['next_action'] is not None for s in trace['steps'])
        entry={'name':name,'input':f'examples/inputs/{source}.json','materials':material_file,'status':result['status'],
               'estimated_total_seconds':result.get('estimated_total_seconds'),'model':trace['model'],
               'actions':[s['action'] for s in trace['steps']],'checks':checks,'passed':all(checks.values()),
               'elapsed_seconds':round(time.perf_counter()-before,3)}
        summary['cases'].append(entry);summary['elapsed_seconds']=round(time.perf_counter()-started,3)
        Path(f'examples/{prefix}_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(entry,ensure_ascii=False),flush=True)
        if trace['steps'] and all(s['action']=='model_error' for s in trace['steps']): break
    return 0 if len(summary['cases'])==len(args.cases) and all(c['passed'] for c in summary['cases']) else 1


if __name__=='__main__': raise SystemExit(main())

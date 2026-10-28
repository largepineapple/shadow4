import argparse
import json
import sys
from pathlib import Path
from .models import validate_request
from .tools import Tools
from .agent import Agent
from .llm_client import LiveClient
from .mock_policy import MockPolicy
from .trace import Trace


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Fact-constrained editable short-video scripts; no publishing')
    parser.add_argument('--mode', choices=['mock','live'], required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--materials')
    parser.add_argument('--trace', required=True)
    parser.add_argument('--output')
    parser.add_argument('--inject-failure', choices=['search_materials','estimate_duration','check_rules'])
    parser.add_argument('--failure-mode', choices=['once','always'], default='always')
    parser.add_argument('--max-steps', type=int, default=16)
    parser.add_argument('--max-tool-calls', type=int, default=14)
    args = parser.parse_args()
    trace = Trace(args.mode,'not_called','invalid-request')
    try:
        request,missing = validate_request(json.loads(Path(args.input).read_text(encoding='utf-8-sig')))
        trace.value['case_id'] = request['request_id']
        if missing:
            result = {'request_id':request['request_id'],'status':'needs_information','approved':False,
                      'missing_fields':missing,'script':None,'knowledge_gaps':['请补充主题、受众、平台、目标时长和风格。'],
                      'risks':[],'draft_history':[],'tool_errors':[],'published':False}
        else:
            tools = Tools(request,args.materials,args.inject_failure,args.failure_mode)
            client = MockPolicy(tools) if args.mode=='mock' else LiveClient()
            trace.value['model'] = client.model
            trace.value['materials'] = Path(args.materials).name if args.materials else 'materials.json'
            result = Agent(tools,client,trace,args.max_steps,args.max_tool_calls).run()
    except Exception as exc:
        result = {'status':'incomplete','approved':False,'script':None,'knowledge_gaps':[str(exc)],'risks':[],'published':False}
    trace.save(args.trace,result)
    rendered = json.dumps(result,ensure_ascii=False,indent=2)
    print(rendered)
    if args.output:
        Path(args.output).parent.mkdir(parents=True,exist_ok=True)
        Path(args.output).write_text(rendered,encoding='utf-8')
    return 0 if result['status'] in ('completed','needs_information','needs_materials','cannot_satisfy') else 1


if __name__=='__main__': raise SystemExit(main())

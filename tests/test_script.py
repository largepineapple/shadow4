import copy
import json
from pathlib import Path
import pytest
from src.models import validate_request,digest
from src.tools import Tools
from src.policy import Policy
from src.agent import Agent
from src.mock_policy import MockPolicy
from src.trace import Trace


def request(name='normal'):
    value=json.loads(Path(f'examples/inputs/{name}.json').read_text(encoding='utf-8'))
    value,missing=validate_request(value)
    assert not missing
    return value


def execute(name='normal',materials=None,failure=None,mode='always',**limits):
    tools=Tools(request(name),materials,failure,mode)
    trace=Trace('mock','deterministic-mock-no-LLM',tools.request['request_id'])
    result=Agent(tools,MockPolicy(tools),trace,**limits).run()
    return result,tools,trace


def retrieve(tools): return tools.execute('search_materials',{'query':'字幕'})


def check(tools,draft):
    estimate=tools.execute('estimate_duration',{'draft':draft})
    did=estimate['data']['draft_id']
    rules=tools.execute('check_rules',{'draft_id':did})
    return did,estimate['data'],rules['data']


def finalize(tools,did,mode='ready'):
    return Policy(tools).finalize({'draft_id':did,'mode':mode,'decision_basis':'Public test summary'})


def draft(tools):
    retrieve(tools)
    return MockPolicy(tools).build_draft()


def test_normal_complete_and_scene_totals():
    result,_,_=execute()
    assert result['status']=='completed' and result['approved'] is True
    assert result['estimated_total_seconds']==28
    assert result['duration_check']['passed'] and result['rule_check']['passed']
    assert sum(s['estimated_seconds'] for s in result['script']['scenes'])+result['duration_check']['transition_seconds']==28
    for scene in result['script']['scenes']:
        assert scene['subtitle']==scene['source_citation']['quote']=='支持字幕'
    assert result['published'] is False


def test_overlong_draft_is_actually_revised_and_rechecked():
    result,_,trace=execute('overlong')
    estimates=[s['observation_summary']['data'] for s in trace.value['steps'] if s['action']=='estimate_duration']
    assert [e['estimated_total_seconds'] for e in estimates]==[38,28]
    assert [e['passed'] for e in estimates]==[False,True]
    assert estimates[0]['draft_id']!=estimates[1]['draft_id']
    assert all(r['rule_check'] is not None for r in result['draft_history'])
    assert result['status']=='completed'


def test_unsupported_efficacy_is_repaired_not_approved():
    result,_,_=execute('rule_repair')
    first=result['draft_history'][0]
    assert not first['rule_check']['passed']
    assert any(r['rule_id']=='UNSUPPORTED_NARRATION' for r in first['rule_check']['risks'])
    assert result['approved']
    assert '80%' not in json.dumps(result['script'],ensure_ascii=False)


@pytest.mark.parametrize('field',['theme','audience','platform','target_seconds','style'])
def test_missing_inputs(field):
    r=request();r.pop(field)
    assert validate_request(r)[1]==[field]


@pytest.mark.parametrize('seconds',[0,-1,True,1.2,'30'])
def test_invalid_target(seconds):
    with pytest.raises(ValueError): validate_request(request()|{'target_seconds':seconds})


def test_no_materials_and_empty_catalog():
    for name,path in [('no_materials',None),('empty_results','examples/fixtures/empty.json')]:
        result,_,_=execute(name,path)
        assert result['status']=='needs_materials'
        assert result['script'] is None and not result['approved']


@pytest.mark.parametrize('tool',['search_materials','estimate_duration','check_rules'])
def test_persistent_tool_failure(tool):
    result,_,_=execute(failure=tool)
    assert result['status']=='tool_failed'
    assert not result['approved'] and result['script'] is None
    assert result['tool_errors']


@pytest.mark.parametrize('tool',['search_materials','estimate_duration','check_rules'])
def test_transient_error_can_recover(tool):
    result,_,_=execute(failure=tool,mode='once')
    assert result['status']=='completed'
    assert len(result['tool_errors'])==1


def test_impossible_target_does_not_approve_empty_video():
    result,_,_=execute('too_short')
    assert result['status']=='cannot_satisfy'
    assert result['estimated_total_seconds']==9
    assert result['script'] is None and result['risks']


def test_changed_source_updates_actual_caption_and_citation():
    result,_,_=execute('changed_source','examples/fixtures/changed.json')
    assert result['status']=='completed'
    assert all(c['quote']=='支持手动添加字幕' for c in result['source_citations'])
    assert all(s['subtitle']=='支持手动添加字幕' for s in result['script']['scenes'])


def test_edit_after_pass_requires_new_checks():
    tools=Tools(request());original=draft(tools)
    did,_,_=check(tools,original)
    assert finalize(tools,did)['ok']
    edited=copy.deepcopy(original);edited['scenes'][0]['narration']='效率提升80%'
    new_id=tools.execute('estimate_duration',{'draft':edited})['data']['draft_id']
    assert new_id!=did
    assert finalize(tools,new_id)['error']['code']=='CHECK_REQUIRED'
    tools.execute('check_rules',{'draft_id':new_id})
    assert finalize(tools,new_id)['error']['code']=='DRAFT_NOT_APPROVED'
    assert tools.drafts[did]['draft']==original


@pytest.mark.parametrize('kind',['target','source','brand'])
def test_changed_check_context_is_rejected(kind):
    tools=Tools(request());did,_,_=check(tools,draft(tools))
    if kind=='target': tools.request['target_seconds']=5
    elif kind=='source': tools.materials['P01']['facts'][0]['text']='支持手动添加字幕'
    else: tools.rules['min_scene_seconds']=15
    assert finalize(tools,did)['error']['code']=='STALE_CHECK'


def test_unretrieved_or_irrelevant_source_cannot_pass():
    tools=Tools(request());template=request('overlong')['initial_draft']
    _,_,rules=check(tools,template)
    assert not rules['passed']
    other=Tools(request('no_materials'));retrieve(other)
    _,_,rules=check(other,template)
    assert any(r['rule_id']=='IRRELEVANT_SOURCE' for r in rules['risks'])


@pytest.mark.parametrize('field',['title','visual','subtitle'])
def test_unsupported_claims_outside_narration_are_rejected(field):
    tools=Tools(request());value=draft(tools)
    if field=='title': value['title']='效率提升80%'
    else: value['scenes'][0][field]='效率提升80%'
    did,_,rules=check(tools,value)
    assert not rules['passed']
    assert not finalize(tools,did)['ok']


@pytest.mark.parametrize('steps,calls',[(1,14),(16,0),(3,14)])
def test_execution_limits_keep_actual_drafts(steps,calls):
    result,_,_=execute(max_steps=steps,max_tool_calls=calls)
    assert result['status']=='incomplete' and not result['approved']
    assert 'limit' in result['knowledge_gaps'][0]
    if steps==3: assert result['draft_history'][0]['rule_check']['passed']

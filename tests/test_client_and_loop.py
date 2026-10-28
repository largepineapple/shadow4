import io
import json
import urllib.error
from unittest.mock import patch
import pytest
from src.llm_client import LiveClient
from src.tools import Tools
from src.agent import Agent
from src.trace import Trace


def req():
    return {'request_id':'test','theme':'字幕功能介绍','audience':'创作者','platform':'douyin','target_seconds':30,'style':'清晰'}


def test_http_error_redacts_key(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-test-credential')
    exc=urllib.error.HTTPError('https://example.invalid',400,'bad',{},io.BytesIO(b'{"error":"synthetic-test-credential sk-synthetic-other"}'))
    with patch('urllib.request.urlopen',side_effect=exc):
        with pytest.raises(RuntimeError) as caught: LiveClient().choose([])
    assert 'synthetic-test-credential' not in str(caught.value)
    assert 'sk-synthetic-other' not in str(caught.value)


def test_tool_api_schema_and_deepseek_mode(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-test-credential')
    monkeypatch.setenv('OPENAI_BASE_URL','https://api.deepseek.com')
    payload={'choices':[{'message':{'tool_calls':[{'id':'c','function':{'name':'search_materials','arguments':'{"query":"subtitle"}'}}]}}]}
    with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as send:
        assert LiveClient().choose([])==('search_materials',{'query':'subtitle'},'c')
    body=json.loads(send.call_args.args[0].data)
    assert body['thinking']=={'type':'disabled'} and not body['parallel_tool_calls']


def test_parallel_response_rejected(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY','synthetic-test-credential')
    with patch('urllib.request.urlopen',return_value=io.BytesIO(b'{"choices":[{"message":{"tool_calls":[{},{}]}}]}')):
        with pytest.raises(ValueError,match='exactly one'): LiveClient().choose([])


def test_model_cannot_mark_unchecked_script_ready():
    class Wrong:
        def choose(self,messages):
            return 'finalize_script',{'draft_id':'invented','mode':'ready','decision_basis':'Passed everything'},'c'
    trace=Trace('mock','wrong-test','test')
    result=Agent(Tools(req()),Wrong(),trace,max_steps=3).run()
    assert result['status']=='incomplete' and result['script'] is None and not result['approved']
    assert all(not s['observation_summary']['ok'] for s in trace.value['steps'])

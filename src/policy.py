import copy
from .tools import ok, fail


class Policy:
    def __init__(self, tools):
        self.tools = tools

    def finalize(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {'draft_id', 'mode', 'decision_basis'}:
            return fail('INVALID_FINAL', 'Unexpected final fields')
        if any(type(v) is not str for v in arguments.values()) or arguments['mode'] not in ('ready', 'stop'):
            return fail('INVALID_FINAL', 'Invalid final action')
        tools = self.tools
        mode, draft_id = arguments['mode'], arguments['draft_id']
        if not any(e['tool'] == 'search_materials' for e in tools.events):
            return fail('SEARCH_REQUIRED', 'Retrieve source facts before concluding')
        if not tools.retrieved.intersection(tools.relevant_ids()):
            if mode != 'stop': return fail('NO_VERIFIED_MATERIAL', 'No relevant retrieved source facts; ask for materials')
            status = 'tool_failed' if tools.errors and not tools.searches else 'needs_materials'
            return ok(self.result(status, None))
        record = tools.drafts.get(draft_id)
        if not record:
            if mode == 'stop' and tools.errors: return ok(self.result('tool_failed', None))
            return fail('CHECK_REQUIRED', 'Generate a draft and run both checks first')
        duration, rules = record['duration_check'], record['rule_check']
        if not duration or not rules:
            if mode == 'stop' and tools.errors: return ok(self.result('tool_failed', record))
            return fail('CHECK_REQUIRED', 'Both duration and rule checks must succeed as tool operations')
        if any(check['context_hash'] != tools.context_hash() for check in (duration, rules)):
            return fail('STALE_CHECK', 'Input, source or brand rules changed; estimate and check again')
        passes = duration['passed'] and rules['passed']
        if mode == 'ready' and not passes:
            return fail('DRAFT_NOT_APPROVED', 'Revise draft and rerun both checks', duration_check=duration, rule_check=rules)
        if mode == 'stop' and passes:
            return fail('FEASIBLE_DRAFT_AVAILABLE', 'This exact draft passed both checks; finalize ready')
        return ok(self.result('completed' if passes else 'cannot_satisfy', record))

    def result(self, status, record, reason=None):
        tools = self.tools
        record = copy.deepcopy(record)
        duration = record['duration_check'] if record else None
        rules = record['rule_check'] if record else None
        risks = copy.deepcopy(rules['risks']) if rules else []
        if duration and not duration['passed']:
            risks.append({'rule_id': 'TIME_LIMIT', 'reason': 'Estimated duration exceeds target', 'over_by_seconds': duration['over_by_seconds']})
        if status == 'tool_failed': risks.append({'rule_id': 'TOOL_FAILURE', 'reason': 'Required tool operation failed'})
        script = None
        if status == 'completed':
            script = copy.deepcopy(record['draft'])
            seconds = {s['scene_id']: s['estimated_seconds'] for s in duration['scene_timings']}
            sources = {s['scene_id']: s for s in rules['source_citations']}
            for scene in script['scenes']:
                scene['estimated_seconds'] = seconds[scene['id']]
                scene['source_citation'] = sources[scene['id']]
        gaps = []
        if status == 'needs_materials': gaps.append('当前检索未获得支持该主题的素材，请补充素材或调整主题。')
        if status == 'tool_failed': gaps.append('工具失败，尚不能确认时长或事实/品牌规则通过。')
        if status == 'cannot_satisfy': gaps.append('当前草稿仍有未满足的时长或规则约束，不能标记为完成。')
        if reason: gaps.append(reason)
        return {'request_id': tools.request['request_id'], 'status': status, 'approved': status == 'completed',
                'script': script, 'estimated_total_seconds': duration['estimated_total_seconds'] if duration else None,
                'target_seconds': tools.request['target_seconds'], 'source_citations': rules['source_citations'] if rules else [],
                'risks': risks, 'knowledge_gaps': gaps, 'duration_check': duration, 'rule_check': rules,
                'last_draft': record['draft'] if record else None,
                'draft_history': copy.deepcopy(list(tools.drafts.values())), 'tool_errors': copy.deepcopy(tools.errors),
                'published': False}

    def incomplete(self, reason):
        record = next(reversed(self.tools.drafts.values()), None) if self.tools.drafts else None
        return self.result('incomplete', record, reason)

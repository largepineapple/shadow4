import copy


class MockPolicy:
    model = 'deterministic-mock-no-LLM'

    def __init__(self, tools): self.tools = tools

    def build_draft(self):
        t = self.tools
        source = next(m for m in t.materials.values() if m['id'] in t.retrieved.intersection(t.relevant_ids()))
        fact = source['facts'][0]
        target = t.request['target_seconds']
        count = 3 if target >= 14 else 2
        holds = [8,9,9] if target == 30 else [max(4,(target-(count-1))//count)]*count
        return {'title': t.rules['allowed_titles'][0], 'scenes': [
            {'id': f'S{i+1}', 'visual': t.rules['allowed_visuals'][i], 'narration': fact['text'],
             'subtitle': fact['text'], 'hold_seconds': holds[i], 'source_id': source['id'], 'fact_id': fact['id']}
            for i in range(count)]}

    def choose(self, messages):
        t = self.tools
        record = next(reversed(t.drafts.values()), None) if t.drafts else None
        draft_id = record['draft_id'] if record else ''
        def finish(mode, basis):
            return 'finalize_script', {'draft_id': draft_id, 'mode': mode, 'decision_basis': basis}, 'mock'
        counts = {}
        for e in t.errors:
            key = (e['tool'], str(e['arguments']))
            counts[key] = counts.get(key,0)+1
        if any(c >= 2 for c in counts.values()): return finish('stop','Repeated tool failure; no false approval')
        if not t.retrieved.intersection(t.relevant_ids()):
            if len(t.searches) >= 2: return finish('stop','No relevant retrieved material; request supporting facts')
            query = t.request['theme'] if not t.searches else ' '.join(t.request['theme'].split())
            return 'search_materials', {'query':query}, 'mock'
        if not record:
            draft = copy.deepcopy(t.request.get('initial_draft')) or self.build_draft()
            return 'estimate_duration', {'draft':draft}, 'mock'
        if not record['duration_check']: return 'estimate_duration', {'draft':record['draft']}, 'mock'
        if not record['rule_check']: return 'check_rules', {'draft_id':draft_id}, 'mock'
        if record['duration_check']['passed'] and record['rule_check']['passed']: return finish('ready','This exact draft passed duration and source/brand checks')
        if len(t.drafts) >= 2 or t.request['target_seconds'] < record['duration_check']['brand_minimum_seconds']:
            return finish('stop','Cannot meet current constraints after checks')
        return 'estimate_duration', {'draft':self.build_draft()}, 'mock'

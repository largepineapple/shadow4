import copy
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from .models import digest, normalize, validate_draft


def ok(data):
    return {'ok': True, 'data': data, 'error': None}


def fail(code, message, **details):
    return {'ok': False, 'data': None, 'error': {'code': code, 'message': message, **details}}


class Tools:
    def __init__(self, request, materials=None, inject_failure=None, failure_mode='always'):
        self.request = copy.deepcopy(request)
        root = Path(__file__).resolve().parents[1] / 'data'
        self.rules = json.loads((root / 'brand_rules.json').read_text(encoding='utf-8'))
        rows = json.loads(Path(materials or root / 'materials.json').read_text(encoding='utf-8-sig'))
        self.materials = {}
        if not isinstance(rows, list): raise ValueError('Materials must be a list')
        for row in rows:
            if not isinstance(row.get('id'), str) or not row['id'] or row['id'] in self.materials:
                raise ValueError('Material IDs must be unique')
            date.fromisoformat(row['version_date'])
            if not isinstance(row.get('keywords'), list) or any(not isinstance(k, str) or not k for k in row['keywords']):
                raise ValueError('Material keywords must be nonempty strings')
            ids = set()
            if not isinstance(row.get('facts'), list) or not row['facts']:
                raise ValueError('Each material requires at least one fact')
            for fact in row['facts']:
                if not isinstance(fact.get('id'), str) or not fact['id'] or fact['id'] in ids or not isinstance(fact.get('text'), str) or not fact['text']:
                    raise ValueError('Invalid or duplicate fact')
                ids.add(fact['id'])
            self.materials[row['id']] = row
        self.retrieved, self.drafts = set(), {}
        self.searches, self.events, self.errors = [], [], []
        self.inject_failure, self.failure_mode = inject_failure, failure_mode
        self.failed_once = set()

    def context_hash(self):
        return digest({'request': self.request, 'rules': self.rules, 'materials': self.materials})

    def relevant_ids(self):
        theme = normalize(self.request['theme'])
        return {m['id'] for m in self.materials.values() if any(normalize(k) in theme for k in m['keywords'])}

    def _fault(self, name):
        if self.inject_failure != name: return False
        previous = name in self.failed_once
        self.failed_once.add(name)
        return self.failure_mode == 'always' or not previous

    def execute(self, name, arguments):
        fields = {'search_materials': {'query'}, 'estimate_duration': {'draft'}, 'check_rules': {'draft_id'}}
        if name not in fields or not isinstance(arguments, dict) or set(arguments) != fields[name]:
            return fail('INVALID_ARGUMENT', 'Unknown tool or fields')
        draft_id = None
        try:
            if name == 'estimate_duration':
                draft = validate_draft(arguments['draft'])
                draft_id = digest(draft)
                self.drafts.setdefault(draft_id, {'draft_id': draft_id, 'draft': copy.deepcopy(draft), 'duration_check': None, 'rule_check': None})
            elif any(type(v) is not str or not v.strip() for v in arguments.values()):
                raise ValueError('Tool text arguments must be nonempty strings')
            result = fail('TOOL_UNAVAILABLE', 'Explicit injected failure', draft_id=draft_id) if self._fault(name) else getattr(self, name)(**arguments)
        except Exception as exc:
            result = fail('TOOL_ERROR', str(exc))
        event = {'tool': name, 'arguments': copy.deepcopy(arguments), 'observation': copy.deepcopy(result)}
        self.events.append(event)
        if not result['ok']: self.errors.append(event)
        return result

    def search_materials(self, query):
        hits = [copy.deepcopy(m) for m in self.materials.values() if any(normalize(k) in normalize(query) for k in m['keywords'])]
        self.retrieved.update(m['id'] for m in hits)
        data = {'query': query, 'hits': hits, 'total_matches': len(hits)}
        self.searches.append(data)
        return ok(data)

    def estimate_duration(self, draft):
        record = self.drafts[digest(draft)]
        timing = []
        for scene in record['draft']['scenes']:
            spoken = len(re.findall(r'[\w]', scene['narration']))
            caption = len(re.findall(r'[\w]', scene['subtitle']))
            speech_seconds = math.ceil(spoken / self.rules['narration_chars_per_second'])
            subtitle_seconds = math.ceil(caption / self.rules['subtitle_chars_per_second'])
            seconds = max(scene['hold_seconds'], speech_seconds, subtitle_seconds, self.rules['min_scene_seconds'])
            timing.append({'scene_id': scene['id'], 'narration_seconds': speech_seconds,
                           'subtitle_seconds': subtitle_seconds, 'hold_seconds': scene['hold_seconds'], 'estimated_seconds': seconds})
        transitions = max(0, len(timing)-1) * self.rules['transition_seconds']
        total = sum(s['estimated_seconds'] for s in timing) + transitions
        data = {'draft_id': record['draft_id'], 'context_hash': self.context_hash(), 'scene_timings': timing,
                'transition_seconds': transitions, 'estimated_total_seconds': total, 'target_seconds': self.request['target_seconds'],
                'over_by_seconds': max(0, total-self.request['target_seconds']), 'passed': total <= self.request['target_seconds'],
                'brand_minimum_seconds': self.rules['min_scenes']*self.rules['min_scene_seconds']+(self.rules['min_scenes']-1)*self.rules['transition_seconds']}
        record['duration_check'] = copy.deepcopy(data)
        return ok(data)

    def check_rules(self, draft_id):
        if draft_id not in self.drafts: return fail('UNKNOWN_DRAFT', 'Estimate this exact draft first')
        draft = self.drafts[draft_id]['draft']
        risks, sources = [], []
        def issue(code, message, scene=None):
            risks.append({'rule_id': code, 'reason': message, 'scene_id': scene})
        if draft['title'] not in self.rules['allowed_titles']: issue('BRAND_TITLE', 'Title is not an approved neutral title')
        if not self.rules['min_scenes'] <= len(draft['scenes']) <= self.rules['max_scenes']: issue('SCENE_COUNT', 'Outside permitted storyboard size')
        for scene in draft['scenes']:
            sid = scene['id']
            if scene['visual'] not in self.rules['allowed_visuals']: issue('UNSUPPORTED_VISUAL', 'Use a neutral approved visual direction', sid)
            if scene['hold_seconds'] < self.rules['min_scene_seconds']: issue('MINIMUM_HOLD', 'Scene hold shorter than brand minimum', sid)
            text = draft['title'] + scene['visual'] + scene['narration'] + scene['subtitle']
            if any(term in text for term in self.rules['banned_terms']): issue('BRAND_PROMISE', 'Prohibited brand promise', sid)
            material = self.materials.get(scene['source_id'])
            fact = next((f for f in material['facts'] if f['id'] == scene['fact_id']), None) if material else None
            if not fact or scene['source_id'] not in self.retrieved:
                issue('UNVERIFIED_SOURCE', 'Fact must come from successful material retrieval', sid)
                continue
            if scene['source_id'] not in self.relevant_ids(): issue('IRRELEVANT_SOURCE', 'Source does not match requested theme', sid)
            if scene['subtitle'] != fact['text']: issue('UNSUPPORTED_SUBTITLE', 'Subtitle must exactly match cited product fact', sid)
            if scene['narration'] not in [fact['text'], *self.rules['neutral_narrations']]: issue('UNSUPPORTED_NARRATION', 'Narration contains unsupported fact or unapproved copy', sid)
            sources.append({'scene_id': sid, 'source_id': material['id'], 'fact_id': fact['id'], 'version_date': material['version_date'],
                            'quote': fact['text'], 'content_sha256': hashlib.sha256(fact['text'].encode()).hexdigest()})
        data = {'draft_id': draft_id, 'context_hash': self.context_hash(), 'passed': not risks, 'risks': risks, 'source_citations': sources}
        self.drafts[draft_id]['rule_check'] = copy.deepcopy(data)
        return ok(data)

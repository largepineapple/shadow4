import hashlib
import json
import re
import unicodedata


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).lower().split())


def validate_draft(value):
    if not isinstance(value, dict) or set(value) != {'title', 'scenes'} or type(value['title']) is not str:
        raise ValueError('Draft requires title and scenes only')
    if not isinstance(value['scenes'], list) or not 1 <= len(value['scenes']) <= 10:
        raise ValueError('Draft scenes must contain 1..10 items')
    ids = set()
    for scene in value['scenes']:
        fields = {'id', 'visual', 'narration', 'subtitle', 'hold_seconds', 'source_id', 'fact_id'}
        if not isinstance(scene, dict) or set(scene) != fields:
            raise ValueError('Unexpected scene fields')
        if any(type(scene[k]) is not str for k in fields - {'hold_seconds'}):
            raise ValueError('Scene text fields must be strings')
        if not re.fullmatch(r'S[1-9][0-9]?', scene['id']) or scene['id'] in ids:
            raise ValueError('Scene IDs must be distinct S1..S99 identifiers')
        ids.add(scene['id'])
        if type(scene['hold_seconds']) is not int or not 1 <= scene['hold_seconds'] <= 180:
            raise ValueError('hold_seconds must be integer 1..180')
        if not scene['narration'] or not scene['subtitle']:
            raise ValueError('Narration and subtitle must be nonempty')
    return value


def validate_request(value):
    allowed = {'request_id', 'theme', 'audience', 'platform', 'target_seconds', 'style', 'initial_draft'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('Unexpected request fields')
    if not isinstance(value.get('request_id'), str) or not value['request_id'].strip():
        raise ValueError('request_id required')
    required = ['theme', 'audience', 'platform', 'target_seconds', 'style']
    missing = [k for k in required if value.get(k) in (None, '')]
    for key in set(required) - {'target_seconds'} - set(missing):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(key + ' must be nonempty text')
    if 'target_seconds' not in missing and (type(value['target_seconds']) is not int or not 1 <= value['target_seconds'] <= 300):
        raise ValueError('target_seconds must be integer 1..300')
    if value.get('initial_draft') is not None:
        validate_draft(value['initial_draft'])
    return value, missing

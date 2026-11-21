"""Explicit per-device temporary memory settings, separate from spending grants."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time


DEFAULT = {'enabled': False, 'ttl_seconds': 43200, 'persist': True,
           'summarize': True, 'background': True, 'supplement': True}
FIELDS = frozenset(DEFAULT)


def binding_key(device_id, client_id, authorization):
    if not all(isinstance(value, str) and 0 < len(value) <= 256
               for value in (device_id, client_id, authorization)):
        raise ValueError('working_memory_binding_required')
    return hashlib.sha256(json.dumps([device_id, client_id, authorization],
                                    separators=(',', ':')).encode()).hexdigest()


class WorkingMemoryPolicyStore:
    """Settings only: no transcript, credential, archive or new paid grant."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'schema': 1, 'bindings': {}}
        if self.path.is_symlink() or self.path.stat().st_size > 65536:
            raise ValueError('working_memory_policy_invalid')
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('schema') != 1 or
                not isinstance(data.get('bindings'), dict) or len(data['bindings']) > 32):
            raise ValueError('working_memory_policy_invalid')
        return data

    @staticmethod
    def validate(values):
        if not isinstance(values, dict) or set(values) != FIELDS:
            raise ValueError('working_memory_policy_fields')
        result = dict(values)
        if any(type(result[key]) is not bool for key in FIELDS-{'ttl_seconds'}):
            raise ValueError('working_memory_policy_boolean')
        if type(result['ttl_seconds']) is not int or not 3600 <= result['ttl_seconds'] <= 86400:
            raise ValueError('working_memory_ttl_range')
        return result

    def get(self, device_id, client_id, authorization):
        key = binding_key(device_id, client_id, authorization)
        with self.lock:
            row = self._read()['bindings'].get(key)
            if row is None:
                return dict(DEFAULT)
            if not isinstance(row, dict) or not FIELDS <= row.keys():
                raise ValueError('working_memory_policy_invalid')
            return self.validate({name: row[name] for name in FIELDS})

    def set(self, device_id, client_id, authorization, values):
        key = binding_key(device_id, client_id, authorization)
        values = self.validate(values)
        with self.lock:
            data = self._read()
            if key not in data['bindings'] and len(data['bindings']) >= 32:
                raise ValueError('working_memory_policy_capacity')
            data['bindings'][key] = {**values, 'updated': time.time()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name+'.tmp')
            if temporary.is_symlink():
                raise ValueError('working_memory_policy_invalid')
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        return values

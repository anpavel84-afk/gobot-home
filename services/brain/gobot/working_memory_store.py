"""Encrypted, expiring checkpoints of an explicitly enabled working scope.

This table is deliberately separate from messages, archive indexes and the debug
journal. Nothing is restored until the server supplies the current scope and
authorization again. Windows DPAPI is required unless a test injects a cipher.
"""
from __future__ import annotations

import json
import time
import zlib


SCHEMA = """
CREATE TABLE IF NOT EXISTS working_memory_checkpoints(
 scope_id TEXT PRIMARY KEY,
 binding_id TEXT NOT NULL,
 authorization_digest TEXT NOT NULL,
 updated REAL NOT NULL,
 expires REAL NOT NULL,
 sealed BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS working_memory_checkpoint_expiry
 ON working_memory_checkpoints(expires);
"""
MAX_PLAIN_BYTES = 20 * 1024 * 1024
MAX_SEALED_BYTES = 6 * 1024 * 1024


class WorkingMemoryStore:
    def __init__(self, memory, *, protect=None, unprotect=None):
        from .secrets_store import _dpapi
        self.memory = memory
        self.protect = protect or _dpapi
        self.unprotect = unprotect or (lambda value: _dpapi(value, decrypt=True))
        self.last_error = None
        with memory.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute('DELETE FROM working_memory_checkpoints WHERE expires<=?', (time.time(),))

    def purge(self, *, scope_id=None, binding_id=None, authorization_digest=None):
        with self.memory.connect() as connection:
            connection.execute('DELETE FROM working_memory_checkpoints WHERE expires<=?', (time.time(),))
            if scope_id is not None:
                connection.execute('DELETE FROM working_memory_checkpoints WHERE scope_id=?', (scope_id,))
            elif binding_id is not None:
                if authorization_digest is None:
                    connection.execute('DELETE FROM working_memory_checkpoints WHERE binding_id=?', (binding_id,))
                else:
                    connection.execute('DELETE FROM working_memory_checkpoints WHERE binding_id=? AND authorization_digest!=?',
                                       (binding_id, authorization_digest))

    def has_checkpoint(self, *, binding_id):
        """Inspect scoped live metadata without loading or decrypting content."""
        if not isinstance(binding_id, str) or not binding_id:
            return False
        with self.memory.connect() as connection:
            row = connection.execute('SELECT 1 FROM working_memory_checkpoints '
                                     'WHERE binding_id=? AND expires>? '
                                     "AND typeof(sealed)='blob' AND length(sealed) BETWEEN 1 AND ? LIMIT 1",
                                     (binding_id, time.time(), MAX_SEALED_BYTES)).fetchone()
        return row is not None

    def load(self, scope_id, binding_id, authorization_digest):
        try:
            self.purge(binding_id=binding_id, authorization_digest=authorization_digest)
            with self.memory.connect() as connection:
                row = connection.execute('SELECT expires,sealed FROM working_memory_checkpoints '
                                         'WHERE scope_id=? AND binding_id=? AND authorization_digest=? AND expires>?',
                                         (scope_id, binding_id, authorization_digest, time.time())).fetchone()
            if row is None:
                return None
            sealed = bytes(row['sealed'])
            if len(sealed) > MAX_SEALED_BYTES:
                raise ValueError('checkpoint_size')
            compressed = self.unprotect(sealed)
            if not isinstance(compressed, bytes) or not compressed.startswith(b'GWM1'):
                raise ValueError('checkpoint_format')
            decoder = zlib.decompressobj()
            raw = decoder.decompress(compressed[4:], MAX_PLAIN_BYTES + 1)
            if len(raw) > MAX_PLAIN_BYTES or decoder.unconsumed_tail or not decoder.eof:
                raise ValueError('checkpoint_size')
            payload = json.loads(raw)
            if (not isinstance(payload, dict) or payload.get('schema') != 1 or
                    payload.get('scope_id') != scope_id or payload.get('expires', 0) <= time.time()):
                raise ValueError('checkpoint_scope')
            self.last_error = None
            return payload
        except Exception:
            # Never fall back to an unprotected copy or disclose exception text.
            self.last_error = 'checkpoint_decryption_unavailable'
            return None

    def save(self, scope_id, binding_id, authorization_digest, payload, expires):
        try:
            raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
            if len(raw) > MAX_PLAIN_BYTES:
                raise ValueError('checkpoint_size')
            sealed = self.protect(b'GWM1' + zlib.compress(raw, level=1))
            if not isinstance(sealed, bytes) or not sealed or len(sealed) > MAX_SEALED_BYTES:
                raise ValueError('checkpoint_cipher')
            with self.memory.connect() as connection:
                connection.execute('DELETE FROM working_memory_checkpoints WHERE expires<=?', (time.time(),))
                connection.execute('INSERT OR REPLACE INTO working_memory_checkpoints '
                                   '(scope_id,binding_id,authorization_digest,updated,expires,sealed) VALUES(?,?,?,?,?,?)',
                                   (scope_id, binding_id, authorization_digest, time.time(), expires, sealed))
            self.last_error = None
            return True
        except Exception:
            self.last_error = 'checkpoint_encryption_or_write_unavailable'
            return False

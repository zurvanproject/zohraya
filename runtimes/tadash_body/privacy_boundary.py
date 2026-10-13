"""Local access boundary for a software body, not a host-security bypass.

Protects only calls through this API. An administrator, the platform, or code
running as the same OS account can bypass it. No network service is started.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import secrets
import stat

from unified_body_v2 import UnifiedBody

MAX_REQUEST_BYTES = 16384
MAX_STATE_BYTES = 64 * 1024 * 1024
MAX_AUDIT_ROWS = 128
EVENT_KEYS = {'event_id', 'at_utc', 'duration_s', 'external', 'requested', 'expected_revision'}


class BoundaryError(ValueError):
    """A request or local store failed a boundary check."""


class PrivateBodyStore:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._check_root()
        except Exception:
            self.close()
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _check_root(self):
        info = os.fstat(self.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise BoundaryError('private directory must be owned by this account and mode 0700')

    @classmethod
    def create(cls, path, body, *, sensor_sources=()):
        if not isinstance(body, UnifiedBody):
            raise BoundaryError('a compatible software body is required')
        sources = sorted(set(sensor_sources))
        if len(sources) > 32 or any(not isinstance(s,str) or not s or len(s)>80 for s in sources):
            raise BoundaryError('bounded sensor source identifiers required')
        # Never adopt, overwrite, chmod, or rewrite an existing user directory.
        Path(path).mkdir(mode=0o700)
        store = cls(path)
        token = secrets.token_urlsafe(32)
        try:
            store._write('policy.json', dict(schema='tadash-privacy-policy/1',
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),sensor_sources=sources))
            store._write('state.json', body.checkpoint())
            store._write('audit.json', [])
            lock = os.open('boundary.lock',os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                           0o600,dir_fd=store.fd)
            os.close(lock)
        except Exception:
            store.close()
            raise
        return store, token

    def _open_file(self, name, flags=os.O_RDONLY):
        try:
            fd = os.open(name, flags | os.O_NOFOLLOW,dir_fd=self.fd)
        except OSError as error:
            raise BoundaryError('private file unavailable or unsafe') from error
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:
            os.close(fd)
            raise BoundaryError('private files must be regular, owned, and mode 0600')
        return fd

    def _read(self, name, maximum):
        fd = self._open_file(name)
        with os.fdopen(fd,'rb') as stream:
            data = stream.read(maximum+1)
        if len(data)>maximum:
            raise BoundaryError('private file size limit exceeded')
        try:
            return json.loads(data)
        except (ValueError,UnicodeDecodeError) as error:
            raise BoundaryError('invalid private file') from error

    def _write(self, name, value):
        data = json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
        if len(data)>MAX_STATE_BYTES:
            raise BoundaryError('private file size limit exceeded')
        temporary = '.write-'+secrets.token_hex(16)
        fd = os.open(temporary,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600,dir_fd=self.fd)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,name,src_dir_fd=self.fd,dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            try:
                os.unlink(temporary,dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def _audit(self, operation, outcome, reason):
        rows = self._read('audit.json',65536)
        if not isinstance(rows,list):
            raise BoundaryError('invalid private audit')
        # Fixed labels only: never retain tokens, request text, samples or state.
        rows.append(dict(at_utc=datetime.now(timezone.utc).isoformat(),
                         operation=operation,outcome=outcome,reason=reason))
        self._write('audit.json',rows[-MAX_AUDIT_ROWS:])

    def _validate_event(self, event, policy):
        if not isinstance(event,dict) or set(event)-EVENT_KEYS or not {'event_id','at_utc','expected_revision'}<=set(event):
            raise BoundaryError('invalid event envelope')
        duration = event.get('duration_s',1.)
        if isinstance(duration,bool) or not isinstance(duration,(float,int)) or not math.isfinite(duration) or not .1<=duration<=5.:
            raise BoundaryError('cycle exceeds boundary budget')
        external = event.get('external',{})
        if not isinstance(external,dict):
            raise BoundaryError('invalid external input')
        sensors = external.get('sensors',{})
        native = external.get('native',{})
        if not isinstance(sensors,dict) or not isinstance(native,dict):
            raise BoundaryError('invalid sensory input')
        samples = list(sensors.values())
        physical = native.get('physical_samples',[])
        if not isinstance(physical,list):
            raise BoundaryError('invalid sensory input')
        samples += physical
        for sample in samples:
            if not isinstance(sample,dict) or sample.get('source_id') not in policy['sensor_sources']:
                raise BoundaryError('unregistered sensory source')

    def handle(self, token, request):
        self._check_root()
        fd = self._open_file('boundary.lock',os.O_RDWR)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            policy = self._read('policy.json',8192)
            if policy.get('schema')!='tadash-privacy-policy/1':
                raise BoundaryError('invalid private policy')
            supplied = hashlib.sha256(token.encode()).hexdigest() if isinstance(token,str) and len(token)<=128 else ''
            if not hmac.compare_digest(supplied,policy['token_sha256']):
                self._audit('unknown','denied','unauthorized')
                raise PermissionError('access denied')
            operation = request.get('op') if isinstance(request,dict) else None
            audit_operation = operation if operation in ('inspect','step') else 'unknown'
            try:
                encoded = json.dumps(request,allow_nan=False).encode()
                if len(encoded)>MAX_REQUEST_BYTES:
                    raise BoundaryError('request size limit exceeded')
                if not isinstance(self._read('audit.json',65536),list):
                    raise BoundaryError('invalid private audit')
                if operation=='inspect' and set(request)=={'op'}:
                    body = UnifiedBody.restore(self._read('state.json',MAX_STATE_BYTES))
                    result = dict(schema='tadash-private-summary/1',revision=body.revision,
                                  system_count=12,regional_count=len(body.bus))
                elif operation=='step' and set(request)=={'op','event'}:
                    event = request['event']
                    self._validate_event(event,policy)
                    body = UnifiedBody.restore(self._read('state.json',MAX_STATE_BYTES))
                    receipt = body.cycle(**event)
                    self._write('state.json',body.checkpoint())
                    result = dict(schema='tadash-private-receipt/1',revision=body.revision,
                        selected_action=receipt['owner']['selected_action'],
                        physical_model_valid=receipt['owner']['physical_model_valid'])
                else:
                    raise BoundaryError('operation not allowed')
            except (ValueError,TypeError,KeyError) as error:
                self._audit(audit_operation,'rejected','invalid_request_or_store')
                raise BoundaryError('request rejected; no private content returned') from error
            self._audit(audit_operation,'accepted','completed')
            return result
        finally:
            os.close(fd)

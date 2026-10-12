"""
SAJHA MCP Server — push-based reload from bucket event notifications.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A cloud storage backend (s3, azure, gcs) is polled by the object-store sync manager
(``S3SyncManager`` in sajha/core/storage.py) every ``storage.s3.sync_interval`` seconds. With
``storage.events.provider`` set, a listener thread also reads the bucket's event notifications
from a queue and hands each changed path to the same sync manager at once, so a change reaches
the registries (and through them the change bus) in seconds instead of up to one interval:

    provider       queue it reads                              SDK (imported lazily)
    sqs            an SQS queue fed by S3 event notifications,  boto3
                   by SNS, or by an EventBridge rule
    azure_queue    a Storage Queue fed by an Event Grid         azure-storage-queue
                   subscription on the storage account
    pubsub         a Pub/Sub pull subscription on the topic     google-cloud-pubsub
                   of a GCS bucket notification

Polling stays on as the fallback; while the listener is healthy the sync manager polls only
every ``storage.events.healthy_poll_interval`` seconds. A missing SDK or incomplete settings
log an info line and raise an ``info`` system notice (``storage.events:<provider>``); they never
stop the server. A queue delivers each message to one consumer, so with a shared state store
the worker that receives a batch relays its paths to every other worker (channel
``storage_events``). Design: docs/getting-started/Storage Guide.md ("Push-based reload").
"""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote, unquote_plus

logger = logging.getLogger(__name__)

PROVIDERS = ('sqs', 'azure_queue', 'pubsub')
AUTO_PROVIDER = {'S3StorageBackend': 'sqs', 'AzureBlobStorageBackend': 'azure_queue',
                 'GCSStorageBackend': 'pubsub'}
SDK_PACKAGE = {'sqs': 'boto3', 'azure_queue': 'azure-storage-queue', 'pubsub': 'google-cloud-pubsub'}
RELAY_CHANNEL = 'storage_events'

#: one parsed notification: (bucket or container, object key, deleted)
ObjectEvent = Tuple[Optional[str], str, bool]


# ── parsers: one notification body -> object events ──────────────────────────

def _json(text: Any) -> Any:
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode('utf-8')
    return json.loads(text)


def parse_s3_message(body: Any) -> List[ObjectEvent]:
    """An SQS message body: an S3 event notification (``Records``), the same wrapped by SNS
    (``Type: Notification``), or an EventBridge event (``source: aws.s3``). ``s3:TestEvent``
    and other event names give nothing."""
    doc = _json(body)
    if isinstance(doc, dict) and doc.get('Type') == 'Notification' and 'Message' in doc:
        doc = _json(doc['Message'])
    out: List[ObjectEvent] = []
    if not isinstance(doc, dict):
        return out
    for rec in doc.get('Records') or []:
        name = str(rec.get('eventName') or '')
        s3 = rec.get('s3') or {}
        key = (s3.get('object') or {}).get('key')
        if not key or not (name.startswith('ObjectCreated') or name.startswith('ObjectRemoved')):
            continue
        # S3 notifications URL-encode the key ('+' for a space)
        out.append(((s3.get('bucket') or {}).get('name'), unquote_plus(key), name.startswith('ObjectRemoved')))
    if doc.get('source') == 'aws.s3' and isinstance(doc.get('detail'), dict):
        kind = str(doc.get('detail-type') or '')
        detail = doc['detail']
        key = (detail.get('object') or {}).get('key')
        if key and kind in ('Object Created', 'Object Deleted'):
            out.append(((detail.get('bucket') or {}).get('name'), key, kind == 'Object Deleted'))
    return out


_BLOB_SUBJECT = '/blobServices/default/containers/'


def parse_event_grid_message(content: Any) -> List[ObjectEvent]:
    """A Storage Queue message from an Event Grid subscription: the Event Grid schema or
    CloudEvents, one event or a list, as JSON or base64-encoded JSON (Event Grid's default)."""
    try:
        doc = _json(content)
    except (ValueError, UnicodeDecodeError):
        doc = _json(base64.b64decode(content))
    out: List[ObjectEvent] = []
    for ev in doc if isinstance(doc, list) else [doc]:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get('eventType') or ev.get('type') or '')
        if kind not in ('Microsoft.Storage.BlobCreated', 'Microsoft.Storage.BlobDeleted'):
            continue
        subject = str(ev.get('subject') or '')
        if not subject.startswith(_BLOB_SUBJECT) or '/blobs/' not in subject:
            continue
        container, _, blob = subject[len(_BLOB_SUBJECT):].partition('/blobs/')
        if blob:
            out.append((container, unquote(blob), kind.endswith('BlobDeleted')))
    return out


def parse_gcs_message(data: Any, attributes: Optional[Dict[str, str]] = None) -> List[ObjectEvent]:
    """A Pub/Sub message of a GCS bucket notification: ``eventType``, ``bucketId`` and
    ``objectId`` in the attributes (the JSON object resource in ``data`` as a fallback).
    ``OBJECT_DELETE`` and ``OBJECT_ARCHIVE`` read as a delete; the sync manager checks whether
    the object still exists, so an overwrite on a versioned bucket is not mistaken for one."""
    attrs = dict(attributes or {})
    kind = attrs.get('eventType', '')
    if kind not in ('OBJECT_FINALIZE', 'OBJECT_DELETE', 'OBJECT_ARCHIVE', 'OBJECT_METADATA_UPDATE'):
        return []
    bucket, key = attrs.get('bucketId'), attrs.get('objectId')
    if not key and data:
        try:
            res = _json(data)
            bucket, key = bucket or res.get('bucket'), res.get('name')
        except (ValueError, AttributeError, UnicodeDecodeError):
            return []
    if not key:
        return []
    return [(bucket, key, kind in ('OBJECT_DELETE', 'OBJECT_ARCHIVE'))]


# ── queue sources: receive / ack against an injected client ──────────────────

class QueueSource:
    """One queue. ``receive()`` returns ``[(handle, [ObjectEvent, ...]), ...]``; ``ack(handles)``
    deletes those messages. ``blocking``: receive itself waits (a long poll)."""
    name = ''
    blocking = False

    def receive(self) -> List[Tuple[Any, List[ObjectEvent]]]:
        raise NotImplementedError

    def ack(self, handles: List[Any]) -> None:
        raise NotImplementedError

    @staticmethod
    def _parse(fn: Callable[..., List[ObjectEvent]], *args) -> List[ObjectEvent]:
        try:
            return fn(*args)
        except Exception as e:        # a message we cannot read is acknowledged and dropped
            logger.debug(f'storage events: unreadable message dropped: {e}')
            return []


class SqsSource(QueueSource):
    name = 'sqs'
    blocking = True

    def __init__(self, client, queue_url: str, wait_seconds: int = 20, max_messages: int = 10):
        self.client, self.queue_url = client, queue_url
        self.wait_seconds = max(0, min(20, int(wait_seconds)))
        self.max_messages = max(1, min(10, int(max_messages)))

    def receive(self):
        resp = self.client.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=self.max_messages,
                                           WaitTimeSeconds=self.wait_seconds) or {}
        return [(m.get('ReceiptHandle'), self._parse(parse_s3_message, m.get('Body') or ''))
                for m in resp.get('Messages') or []]

    def ack(self, handles):
        handles = [h for h in handles if h]
        for i in range(0, len(handles), 10):
            batch = handles[i:i + 10]
            self.client.delete_message_batch(QueueUrl=self.queue_url, Entries=[
                {'Id': str(n), 'ReceiptHandle': h} for n, h in enumerate(batch)])


class AzureQueueSource(QueueSource):
    name = 'azure_queue'

    def __init__(self, client, max_messages: int = 32, visibility_timeout: int = 60):
        self.client = client
        self.max_messages = max(1, min(32, int(max_messages)))
        self.visibility_timeout = int(visibility_timeout)

    def receive(self):
        out = []
        for i, msg in enumerate(self.client.receive_messages(messages_per_page=self.max_messages,
                                                             visibility_timeout=self.visibility_timeout)):
            out.append((msg, self._parse(parse_event_grid_message, msg.content)))
            if i + 1 >= self.max_messages:
                break
        return out

    def ack(self, handles):
        for msg in handles:
            self.client.delete_message(msg)


class PubSubSource(QueueSource):
    name = 'pubsub'
    blocking = True

    def __init__(self, client, subscription: str, wait_seconds: int = 20, max_messages: int = 50):
        self.client, self.subscription = client, subscription
        self.wait_seconds = max(1, int(wait_seconds))
        self.max_messages = max(1, int(max_messages))

    def receive(self):
        try:
            resp = self.client.pull(request={'subscription': self.subscription, 'max_messages': self.max_messages},
                                    timeout=self.wait_seconds + 5)
        except Exception as e:
            if type(e).__name__ == 'DeadlineExceeded':      # nothing arrived within the wait
                return []
            raise
        return [(r.ack_id, self._parse(parse_gcs_message, r.message.data, dict(r.message.attributes or {})))
                for r in getattr(resp, 'received_messages', None) or []]

    def ack(self, handles):
        handles = [h for h in handles if h]
        if handles:
            self.client.acknowledge(request={'subscription': self.subscription, 'ack_ids': handles})


# ── settings and the SDK factories ───────────────────────────────────────────

def _setting(config, key: str, default: str = '') -> str:
    from sajha.core.storage import storage_setting
    return storage_setting(config, key, default)


def _int(config, key: str, default: int) -> int:
    try:
        return int(float(_setting(config, key, str(default)) or default))
    except (TypeError, ValueError):
        return default


def resolve_provider(config, backend) -> str:
    """'' (push off) or one of PROVIDERS; ``auto`` follows the backend."""
    p = (_setting(config, 'storage.events.provider', 'none') or 'none').strip().lower()
    if p in ('', 'none', 'off', 'false'):
        return ''
    if p == 'auto':
        return AUTO_PROVIDER.get(type(backend).__name__, '')
    if p not in PROVIDERS:
        raise ValueError(f'storage.events.provider: unknown provider {p!r} (none, auto, {", ".join(PROVIDERS)})')
    return p


class EventsUnavailable(Exception):
    """The listener cannot start (SDK missing, settings incomplete); polling carries on."""


def build_source(provider: str, config) -> QueueSource:
    wait = _int(config, 'storage.events.wait_seconds', 20)
    maxm = _int(config, 'storage.events.max_messages', 10)
    if provider == 'sqs':
        url = _setting(config, 'storage.events.sqs.queue_url')
        if not url:
            raise EventsUnavailable('storage.events.sqs.queue_url is not set')
        try:
            import boto3
        except ImportError:
            raise EventsUnavailable('boto3 is not installed (pip install boto3)')
        region = _setting(config, 'storage.events.sqs.region') or _setting(config, 'storage.s3.region', 'us-east-1')
        client = boto3.client('sqs', region_name=region,
                              endpoint_url=_setting(config, 'storage.events.sqs.endpoint_url') or None)
        return SqsSource(client, url, wait, maxm)
    if provider == 'azure_queue':
        queue = _setting(config, 'storage.events.azure.queue_name')
        if not queue:
            raise EventsUnavailable('storage.events.azure.queue_name is not set')
        try:
            from azure.storage.queue import QueueClient
        except ImportError:
            raise EventsUnavailable('azure-storage-queue is not installed (pip install azure-storage-queue)')
        conn = (_setting(config, 'storage.events.azure.connection_string')
                or _setting(config, 'storage.azure.connection_string'))
        if conn:
            client = QueueClient.from_connection_string(conn, queue)
        else:
            url = _setting(config, 'storage.events.azure.account_url') or \
                _setting(config, 'storage.azure.account_url').replace('.blob.', '.queue.')
            if not url:
                raise EventsUnavailable('storage.events.azure.account_url (or a connection string) is not set')
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError:
                raise EventsUnavailable('azure-identity is not installed (pip install azure-identity)')
            client = QueueClient(account_url=url, queue_name=queue, credential=DefaultAzureCredential())
        return AzureQueueSource(client, max(maxm, 1))
    if provider == 'pubsub':
        sub = _setting(config, 'storage.events.pubsub.subscription')
        if not sub:
            raise EventsUnavailable('storage.events.pubsub.subscription is not set')
        if not sub.startswith('projects/'):
            project = _setting(config, 'storage.events.pubsub.project') or _setting(config, 'storage.gcs.project')
            if not project:
                raise EventsUnavailable('give storage.events.pubsub.subscription as projects/<p>/subscriptions/<s>, '
                                        'or set storage.events.pubsub.project')
            sub = f'projects/{project}/subscriptions/{sub}'
        try:
            from google.cloud import pubsub_v1
        except ImportError:
            raise EventsUnavailable('google-cloud-pubsub is not installed (pip install google-cloud-pubsub)')
        return PubSubSource(pubsub_v1.SubscriberClient(), sub, wait, maxm)
    raise EventsUnavailable(f'unknown provider {provider!r}')


# ── listeners for every pushed path (workflow file triggers, DuckDB storage sources) ──

_path_listeners: List[Callable[[List[str]], None]] = []
_path_lock = threading.Lock()


def add_path_listener(fn: Callable[[List[str]], None]) -> None:
    """``fn(paths)`` for every batch of changed storage paths a push delivers (any prefix)."""
    with _path_lock:
        if fn not in _path_listeners:
            _path_listeners.append(fn)


def remove_path_listener(fn: Callable[[List[str]], None]) -> None:
    with _path_lock:
        if fn in _path_listeners:
            _path_listeners.remove(fn)


def emit_paths(paths: List[str]) -> None:
    with _path_lock:
        fns = list(_path_listeners)
    for fn in fns:
        try:
            fn(list(paths))
        except Exception as e:
            logger.warning(f'storage events: a path listener failed: {e}')


# ── the listener ─────────────────────────────────────────────────────────────

def _notice(provider: str, severity: str, title: str, detail: str) -> None:
    try:
        from sajha import notices
        from sajha.core.state import WORKER_ID
        notices.raise_notice(f'storage.events:{provider}', severity=severity, source='storage', title=title,
                             detail=detail, link='/help/guides/Storage%20Guide.md', ttl_minutes=0, holder=WORKER_ID)
    except Exception:
        pass


def _clear_notice(provider: str) -> None:
    try:
        from sajha import notices
        from sajha.core.state import WORKER_ID
        notices.clear_notice(f'storage.events:{provider}', holder=WORKER_ID)
    except Exception:
        pass


class StorageEvents:
    """Reads one queue, maps object keys to storage paths and applies them through ``sync``
    (an ``S3SyncManager``) and the path listeners."""

    #: consecutive failed receives before the listener counts as unhealthy and says so
    FAILURES_BEFORE_NOTICE = 3

    def __init__(self, backend, source: QueueSource, sync=None, idle_seconds: float = 20.0,
                 relay: bool = True):
        self.backend, self.source, self.sync = backend, source, sync
        self.idle_seconds = max(0.05, float(idle_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_ok: float = 0.0
        self.failures = 0
        self.received = 0           # messages read
        self.applied = 0            # paths applied
        self.origin = uuid.uuid4().hex
        self._relay_store = None
        self._unsubscribe = None
        if relay:
            self._attach_relay()

    # -- key mapping ---------------------------------------------------

    def _bucket(self) -> Optional[str]:
        return getattr(self.backend, 'bucket', None) or getattr(self.backend, 'container', None)

    def path_for(self, bucket: Optional[str], key: str) -> Optional[str]:
        """The storage-relative path of an object of this backend, or None (another bucket, or
        outside the configured prefix)."""
        mine = self._bucket()
        if bucket and mine and bucket != mine:
            return None
        prefix = (getattr(self.backend, 'prefix', '') or '').strip('/')
        if prefix:
            if not key.startswith(prefix + '/'):
                return None
            key = key[len(prefix) + 1:]
        return key or None

    # -- one cycle -----------------------------------------------------

    def poll_once(self) -> int:
        """Receive one batch, apply it, acknowledge it; the number of paths applied. Raises on a
        receive error (the loop counts it)."""
        batch = self.source.receive()
        self.last_ok, self.failures = time.time(), 0
        if not batch:
            return 0
        self.received += len(batch)
        changes: Dict[str, bool] = {}
        for _handle, events in batch:
            for bucket, key, deleted in events:
                path = self.path_for(bucket, key)
                if path:
                    changes[path] = deleted          # the latest event for a path wins
        try:
            if changes:
                self.apply(changes, relay=True)
        finally:
            self.source.ack([h for h, _ in batch])
        return len(changes)

    def apply(self, changes: Dict[str, bool], relay: bool = False) -> None:
        items = sorted(changes.items())
        if self.sync is not None:
            try:
                self.sync.notify(items)
            except Exception as e:
                logger.warning(f'storage events: applying {len(items)} change(s) failed: {e}', exc_info=True)
        emit_paths([p for p, _ in items])
        self.applied += len(items)
        if relay:
            self._relay(changes)

    # -- other workers -------------------------------------------------

    def _attach_relay(self) -> None:
        try:
            from sajha.core.state import get_state_store
            store = get_state_store()
        except Exception:
            return
        if not getattr(store, 'shared', False):
            return

        def on_message(msg: Dict[str, Any]) -> None:
            if msg.get('origin') == self.origin or not isinstance(msg.get('changes'), dict):
                return
            self.apply({str(k): bool(v) for k, v in msg['changes'].items()}, relay=False)

        try:
            self._unsubscribe = store.subscribe(RELAY_CHANNEL, on_message)
            self._relay_store = store
        except Exception as e:
            logger.warning(f'storage events: cannot relay to other workers: {e}')

    def _relay(self, changes: Dict[str, bool]) -> None:
        if self._relay_store is None:
            return
        try:
            self._relay_store.publish(RELAY_CHANNEL, {'origin': self.origin, 'changes': changes})
        except Exception as e:
            logger.warning(f'storage events: relay to other workers failed: {e}')

    # -- health --------------------------------------------------------

    def healthy(self) -> bool:
        """The last receive succeeded recently (within three waits, at least a minute)."""
        if self._thread is None or not self._thread.is_alive() or self.failures:
            return False
        return time.time() - self.last_ok <= max(60.0, 3 * self.idle_seconds)

    def status(self) -> Dict[str, Any]:
        return {'provider': self.source.name, 'healthy': self.healthy(), 'last_ok': self.last_ok or None,
                'failures': self.failures, 'received': self.received, 'applied': self.applied,
                'relay': self._relay_store is not None}

    # -- thread --------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                n = self.poll_once()
                if self._noticed:
                    _clear_notice(self.source.name)
                    self._noticed = False
                if not self.source.blocking and n == 0:
                    self._stop.wait(self.idle_seconds)
            except Exception as e:
                self.failures += 1
                logger.warning(f'storage events ({self.source.name}): receive failed ({self.failures}): {e}')
                if self.failures == self.FAILURES_BEFORE_NOTICE:
                    self._noticed = True
                    _notice(self.source.name, 'warning', 'Bucket event notifications are failing',
                            f'The {self.source.name} listener failed {self.failures} receives in a row ({e}). '
                            f'Changes in the bucket still arrive by polling (storage.s3.sync_interval). '
                            f'Check the queue settings under storage.events and the identity\'s permissions.')
                self._stop.wait(min(60.0, 2.0 ** min(self.failures, 6)))

    _noticed = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f'storage-events-{self.source.name}')
        self._thread.start()
        logger.info(f'Storage events: {self.source.name} listener started')

    def stop(self) -> None:
        self._stop.set()
        if self._unsubscribe is not None:
            try:
                self._unsubscribe()
            except Exception:
                pass
            self._unsubscribe = None
        if self._thread:
            self._thread.join(timeout=5)


_active: Optional[StorageEvents] = None


def get_storage_events() -> Optional[StorageEvents]:
    return _active


def start_storage_events(config, backend, sync=None, source: Optional[QueueSource] = None) -> Optional[StorageEvents]:
    """Start the listener configured under ``storage.events`` for ``backend``, or return None
    (push off, a local backend, or unavailable: logged and noticed, never raised)."""
    global _active
    from sajha.core.storage import LocalStorageBackend
    try:
        provider = '' if isinstance(backend, LocalStorageBackend) else resolve_provider(config, backend)
    except ValueError as e:
        logger.warning(str(e))
        provider = ''
    for other in PROVIDERS:           # a notice of a provider no longer configured ends here
        if other != provider:
            _clear_notice(other)
    if not provider:
        return None
    try:
        src = source or build_source(provider, config)
    except EventsUnavailable as e:
        logger.info(f'Storage events ({provider}) not started: {e}; changes arrive by polling')
        _notice(provider, 'info', 'Bucket event notifications are not active',
                f'storage.events.provider is {provider}, but the listener could not start: {e}. '
                f'Changes in the bucket still arrive by polling (storage.s3.sync_interval).')
        return None
    except Exception as e:
        logger.warning(f'Storage events ({provider}) not started: {e}', exc_info=True)
        return None
    _clear_notice(provider)
    ev = StorageEvents(backend, src, sync, idle_seconds=_int(config, 'storage.events.wait_seconds', 20))
    if sync is not None and hasattr(sync, 'set_push'):
        sync.set_push(ev.healthy, _int(config, 'storage.events.healthy_poll_interval', 600))
    ev.start()
    _active = ev
    return ev


def stop_storage_events() -> None:
    global _active
    if _active is not None:
        _active.stop()
        _active = None

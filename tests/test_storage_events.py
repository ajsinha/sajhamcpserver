# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Push-based reload (sajha/core/storage_events.py): bucket event notifications from SQS, an
Azure Storage Queue or a Pub/Sub subscription feed the object-store sync manager, which fires
the same reload callbacks as its poll. Fake queue clients only; no cloud calls.
"""

import base64
import json
import time

import pytest

from sajha.core import storage_events as se
from sajha.core.storage import S3SyncManager, _ObjectStorageBackend


class Memory(_ObjectStorageBackend):
    """An in-memory object store with a bucket name and a key prefix."""

    def __init__(self, cache_dir, prefix='sajha', bucket='bkt'):
        super().__init__(prefix, str(cache_dir))
        self.bucket = bucket
        self.objs, self.times, self.clock = {}, {}, 0

    def _fetch_bytes(self, key):
        if key not in self.objs:
            raise FileNotFoundError(key)
        return self.objs[key]

    def _store_bytes(self, key, data):
        self.clock += 1
        self.objs[key], self.times[key] = data, float(self.clock)

    def _object_exists(self, key):
        return key in self.objs

    def _delete_object(self, key):
        return self.objs.pop(key, None) is not None

    def _list_keys(self, prefix):
        return [k for k in self.objs if k.startswith(prefix)]

    def _object_mtime(self, key):
        return self.times.get(key, 0.0)


# ── parsers ──────────────────────────────────────────────────────────────────

def _s3_record(key, name='ObjectCreated:Put', bucket='bkt'):
    return {'eventName': name, 's3': {'bucket': {'name': bucket}, 'object': {'key': key}}}


def test_s3_notification_sns_and_eventbridge_parse():
    body = json.dumps({'Records': [_s3_record('sajha/config/tools/a+b%281%29.json'),
                                   _s3_record('sajha/config/tools/x.json', 'ObjectRemoved:Delete'),
                                   _s3_record('sajha/other', 'ObjectRestore:Post')]})
    assert se.parse_s3_message(body) == [('bkt', 'sajha/config/tools/a b(1).json', False),
                                         ('bkt', 'sajha/config/tools/x.json', True)]
    sns = json.dumps({'Type': 'Notification', 'Message': body})
    assert len(se.parse_s3_message(sns)) == 2
    eb = json.dumps({'source': 'aws.s3', 'detail-type': 'Object Deleted',
                     'detail': {'bucket': {'name': 'bkt'}, 'object': {'key': 'sajha/config/prompts/p.json'}}})
    assert se.parse_s3_message(eb) == [('bkt', 'sajha/config/prompts/p.json', True)]
    assert se.parse_s3_message(json.dumps({'Service': 'Amazon S3', 'Event': 's3:TestEvent'})) == []


def test_event_grid_parse_plain_and_base64():
    ev = [{'eventType': 'Microsoft.Storage.BlobCreated',
           'subject': '/blobServices/default/containers/cont/blobs/sajha/config/tools/t.json'},
          {'type': 'Microsoft.Storage.BlobDeleted',            # CloudEvents schema
           'subject': '/blobServices/default/containers/cont/blobs/sajha/config/tools/u.json'},
          {'eventType': 'Microsoft.Storage.BlobTierChanged', 'subject': '/blobServices/default/containers/c/blobs/x'}]
    want = [('cont', 'sajha/config/tools/t.json', False), ('cont', 'sajha/config/tools/u.json', True)]
    assert se.parse_event_grid_message(json.dumps(ev)) == want
    assert se.parse_event_grid_message(base64.b64encode(json.dumps(ev).encode()).decode()) == want


def test_gcs_parse_attributes_and_payload():
    assert se.parse_gcs_message(b'', {'eventType': 'OBJECT_FINALIZE', 'bucketId': 'b',
                                      'objectId': 'sajha/config/tools/t.json'}) == [('b', 'sajha/config/tools/t.json', False)]
    assert se.parse_gcs_message(json.dumps({'bucket': 'b', 'name': 'k'}).encode(),
                                {'eventType': 'OBJECT_DELETE'}) == [('b', 'k', True)]
    assert se.parse_gcs_message(b'', {'eventType': 'OTHER', 'objectId': 'k'}) == []


# ── fake clients ─────────────────────────────────────────────────────────────

class FakeSqs:
    def __init__(self):
        self.queue, self.deleted, self.fail = [], [], 0

    def send(self, body):
        self.queue.append({'Body': body, 'ReceiptHandle': f'rh{len(self.queue)}-{time.time()}'})

    def receive_message(self, QueueUrl, MaxNumberOfMessages, WaitTimeSeconds):
        if self.fail:
            self.fail -= 1
            raise RuntimeError('queue unreachable')
        msgs, self.queue = self.queue[:MaxNumberOfMessages], self.queue[MaxNumberOfMessages:]
        if not msgs:
            time.sleep(0.01)
        return {'Messages': msgs} if msgs else {}

    def delete_message_batch(self, QueueUrl, Entries):
        self.deleted.extend(e['ReceiptHandle'] for e in Entries)


class _AzMsg:
    def __init__(self, content):
        self.content = content


class FakeAzureQueue:
    def __init__(self):
        self.queue, self.deleted = [], []

    def receive_messages(self, messages_per_page, visibility_timeout):
        msgs, self.queue = self.queue[:messages_per_page], self.queue[messages_per_page:]
        return iter(msgs)

    def delete_message(self, msg):
        self.deleted.append(msg)


class _PsMsg:
    def __init__(self, data, attributes):
        self.data, self.attributes = data, attributes


class _Received:
    def __init__(self, ack_id, msg):
        self.ack_id, self.message = ack_id, msg


class FakeSubscriber:
    def __init__(self):
        self.queue, self.acked = [], []

    def pull(self, request, timeout):
        msgs, self.queue = self.queue[:request['max_messages']], self.queue[request['max_messages']:]
        return type('R', (), {'received_messages': msgs})()

    def acknowledge(self, request):
        self.acked.extend(request['ack_ids'])


@pytest.fixture
def world(tmp_path):
    backend = Memory(tmp_path / 'cache')
    sync = S3SyncManager(backend, interval=3600)
    calls = []
    sync.watch('config/tools', lambda: calls.append('tools'))
    sync.watch('config/prompts', lambda: calls.append('prompts'))
    return backend, sync, calls


def test_sqs_event_reloads_the_watched_prefix_once_and_acks(world):
    backend, sync, calls = world
    backend.write_text('config/tools/a.json', '{"name": "a"}')
    backend.write_text('config/tools/b.json', '{"name": "b"}')
    sqs = FakeSqs()
    sqs.send(json.dumps({'Records': [_s3_record('sajha/config/tools/a.json'), _s3_record('sajha/config/tools/b.json')]}))
    sqs.send(json.dumps({'Records': [_s3_record('sajha/data/x.csv')]}))                 # not watched
    sqs.send(json.dumps({'Records': [_s3_record('elsewhere/config/tools/c.json')]}))     # outside the prefix
    sqs.send(json.dumps({'Records': [_s3_record('sajha/config/tools/d.json', bucket='other')]}))
    sqs.send('not json')
    ev = se.StorageEvents(backend, se.SqsSource(sqs, 'url'), sync, relay=False)
    seen = []
    se.add_path_listener(seen.append)
    try:
        assert ev.poll_once() == 3
    finally:
        se.remove_path_listener(seen.append)
    assert calls == ['tools']                       # one reload for the batch, prompts untouched
    assert sorted(seen[0]) == ['config/tools/a.json', 'config/tools/b.json', 'data/x.csv']
    assert len(sqs.deleted) == 5                    # every message acknowledged, the unreadable one too
    assert (backend.cache_dir / 'config/tools/a.json').exists()
    assert sync._timestamps['config/tools/a.json'] == backend.get_modified_time('config/tools/a.json')


def test_a_delete_event_drops_the_cache_and_a_stale_delete_is_a_change(world):
    backend, sync, calls = world
    backend.write_text('config/tools/a.json', '{}')
    sync.notify([('config/tools/a.json', False)])
    backend.delete('config/tools/a.json')
    backend.write_text('config/tools/a.json', '{}')            # recreated before the delete arrived
    sync.notify([('config/tools/a.json', True)])
    assert 'config/tools/a.json' in sync._timestamps
    backend._delete_object(backend._key('config/tools/a.json'))
    sync.notify([('config/tools/a.json', True)])
    assert 'config/tools/a.json' not in sync._timestamps
    assert not (backend.cache_dir / 'config/tools/a.json').exists()
    assert calls == ['tools', 'tools', 'tools']


def test_azure_queue_and_pubsub_sources(world):
    backend, sync, calls = world
    backend.container = backend.bucket = 'cont'
    backend.write_text('config/prompts/p.json', '{}')
    az = FakeAzureQueue()
    content = base64.b64encode(json.dumps([{'eventType': 'Microsoft.Storage.BlobCreated',
                                             'subject': '/blobServices/default/containers/cont/blobs/sajha/config/prompts/p.json'}]).encode()).decode()
    az.queue.append(_AzMsg(content))
    assert se.StorageEvents(backend, se.AzureQueueSource(az), sync, relay=False).poll_once() == 1
    assert calls == ['prompts'] and len(az.deleted) == 1

    backend.bucket = 'gb'
    backend.write_text('config/tools/t.json', '{}')
    sub = FakeSubscriber()
    sub.queue.append(_Received('ack1', _PsMsg(b'', {'eventType': 'OBJECT_FINALIZE', 'bucketId': 'gb',
                                                    'objectId': 'sajha/config/tools/t.json'})))
    assert se.StorageEvents(backend, se.PubSubSource(sub, 'projects/p/subscriptions/s'), sync, relay=False).poll_once() == 1
    assert calls == ['prompts', 'tools'] and sub.acked == ['ack1']


def test_the_listener_thread_is_healthy_and_lengthens_polling(world, monkeypatch):
    backend, sync, calls = world
    sync.interval = 60
    backend.write_text('config/tools/a.json', '{}')
    sqs = FakeSqs()
    sqs.send(json.dumps({'Records': [_s3_record('sajha/config/tools/a.json')]}))
    ev = se.StorageEvents(backend, se.SqsSource(sqs, 'url', wait_seconds=0), sync, relay=False)
    sync.set_push(ev.healthy, 600)
    assert sync.current_interval() == 60            # not started yet: not healthy
    ev.start()
    try:
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        assert calls == ['tools']
        assert ev.healthy() and sync.current_interval() == 600
        assert ev.status()['provider'] == 'sqs'
    finally:
        ev.stop()
    assert not ev.healthy() and sync.current_interval() == 60


def test_repeated_receive_failures_raise_a_notice(world, monkeypatch):
    backend, sync, _ = world
    raised, cleared = [], []
    monkeypatch.setattr(se, '_notice', lambda p, sev, t, d: raised.append((p, sev)))
    monkeypatch.setattr(se, '_clear_notice', lambda p: cleared.append(p))
    sqs = FakeSqs()
    sqs.fail = 3
    ev = se.StorageEvents(backend, se.SqsSource(sqs, 'url', wait_seconds=0), sync, relay=False)
    monkeypatch.setattr(ev._stop, 'wait', lambda t=None: ev._stop.is_set())    # no back-off in the test
    ev.start()
    try:
        deadline = time.time() + 5
        while not cleared and time.time() < deadline:
            time.sleep(0.01)
    finally:
        ev.stop()
    assert raised == [('sqs', 'warning')] and cleared == ['sqs']


def test_relay_to_other_workers(world):
    backend, sync, calls = world
    backend.write_text('config/tools/a.json', '{}')

    class Store:
        shared = True

        def __init__(self):
            self.handlers = []

        def subscribe(self, channel, fn):
            self.handlers.append(fn)
            return lambda: self.handlers.remove(fn)

        def publish(self, channel, msg):
            for fn in list(self.handlers):
                fn(msg)

    store = Store()
    a = se.StorageEvents(backend, se.SqsSource(FakeSqs(), 'u'), sync, relay=False)
    other_calls = []
    sync_b = S3SyncManager(backend, interval=3600)
    sync_b.watch('config/tools', lambda: other_calls.append('tools'))
    b = se.StorageEvents(backend, se.SqsSource(FakeSqs(), 'u'), sync_b, relay=False)
    for ev in (a, b):                     # what _attach_relay does with a shared state store
        ev._relay_store = store
        store.subscribe(se.RELAY_CHANNEL, (lambda e: lambda m: m.get('origin') != e.origin and e.apply(m['changes']))(ev))
    a.apply({'config/tools/a.json': False}, relay=True)
    assert calls == ['tools'] and other_calls == ['tools']


# ── start-up: import-safe, settings, missing SDK ─────────────────────────────

class Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_provider_resolution_and_missing_settings(world, monkeypatch):
    backend, sync, _ = world
    from sajha.core.storage import LocalStorageBackend
    for k in list(__import__('os').environ):
        if k.startswith('SAJHA_STORAGE_EVENTS'):
            monkeypatch.delenv(k)
    assert se.resolve_provider(Cfg(), backend) == ''
    assert se.resolve_provider(Cfg({'storage.events.provider': 'pubsub'}), backend) == 'pubsub'
    with pytest.raises(ValueError):
        se.resolve_provider(Cfg({'storage.events.provider': 'kafka'}), backend)
    assert se.start_storage_events(Cfg({'storage.events.provider': 'sqs'}), LocalStorageBackend('.')) is None
    noticed = []
    monkeypatch.setattr(se, '_notice', lambda p, sev, t, d: noticed.append((p, sev, d)))
    assert se.start_storage_events(Cfg({'storage.events.provider': 'sqs'}), backend, sync) is None
    assert noticed and noticed[0][:2] == ('sqs', 'info') and 'queue_url' in noticed[0][2]


def test_a_missing_sdk_is_an_info_notice_not_an_error(world, monkeypatch):
    import builtins
    backend, sync, _ = world
    real = builtins.__import__

    def no_sdk(name, *a, **kw):
        if name in ('boto3', 'azure.storage.queue', 'google.cloud') or name.startswith('google.cloud.pubsub'):
            raise ImportError(name)
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, '__import__', no_sdk)
    noticed = []
    monkeypatch.setattr(se, '_notice', lambda p, sev, t, d: noticed.append((p, sev)))
    cfg = Cfg({'storage.events.provider': 'sqs', 'storage.events.sqs.queue_url': 'https://q',
               'storage.events.azure.queue_name': 'q', 'storage.events.azure.connection_string': 'x',
               'storage.events.pubsub.subscription': 'projects/p/subscriptions/s'})
    for p in ('sqs', 'azure_queue', 'pubsub'):
        cfg['storage.events.provider'] = p
        assert se.start_storage_events(cfg, backend, sync) is None
    assert noticed == [('sqs', 'info'), ('azure_queue', 'info'), ('pubsub', 'info')]


def test_start_with_an_injected_source(world):
    backend, sync, calls = world
    backend.write_text('config/tools/a.json', '{}')
    sqs = FakeSqs()
    sqs.send(json.dumps({'Records': [_s3_record('sajha/config/tools/a.json')]}))
    ev = se.start_storage_events(Cfg({'storage.events.provider': 'sqs', 'storage.events.wait_seconds': '0'}),
                                 backend, sync, source=se.SqsSource(sqs, 'u', wait_seconds=0))
    try:
        assert ev is not None and se.get_storage_events() is ev
        deadline = time.time() + 5
        while not calls and time.time() < deadline:
            time.sleep(0.01)
        assert calls == ['tools']
    finally:
        se.stop_storage_events()
    assert se.get_storage_events() is None

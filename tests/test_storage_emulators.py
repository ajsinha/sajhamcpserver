# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Storage backends against emulators (Roadmap L1). One contract, run on every backend that is
available here:

* the in-memory object store (always), so the contract itself is tested in every run;
* S3 under moto (``pip install "moto[s3,sqs]" boto3``), including bucket events through SQS;
* S3-compatible MinIO when ``SAJHA_TEST_S3_ENDPOINT`` is set (with ``AWS_ACCESS_KEY_ID`` /
  ``AWS_SECRET_ACCESS_KEY``);
* Azure Blob on Azurite when ``SAJHA_TEST_AZURITE`` holds its connection string
  (``pip install azure-storage-blob``);
* GCS on fake-gcs-server when ``STORAGE_EMULATOR_HOST`` is set (``pip install google-cloud-storage``).

The CI recipe is in docs/getting-started/Storage Guide.md ("Testing the backends").
"""

import json
import os
import uuid

import pytest

from tests.test_storage_events import Memory


def _contract(b):
    b.write_text('config/tools/a.json', '{"name": "a"}')
    b.write_json('config/tools/f/b.json', {'name': 'b'})
    b.write_bytes('data/x.bin', b'\x00\x01')
    assert b.list_files('config/tools', '*.json') == ['config/tools/a.json', 'config/tools/f/b.json']
    assert b.read_json('config/tools/f/b.json') == {'name': 'b'}
    assert b.read_bytes('data/x.bin') == b'\x00\x01'
    assert b.exists('config/tools/a.json') and not b.exists('config/tools/zz.json')
    assert b.get_modified_time('config/tools/a.json') > 0
    assert b.get_local_path('config/tools/a.json').read_text() == '{"name": "a"}'
    with pytest.raises(FileNotFoundError):
        b.read_bytes('config/tools/missing.json')
    assert b.delete('config/tools/a.json') and not b.exists('config/tools/a.json')
    assert b.list_files('config/tools', '*.json') == ['config/tools/f/b.json']


def test_contract_on_the_memory_store(tmp_path):
    _contract(Memory(tmp_path))


@pytest.fixture
def moto_aws(monkeypatch):
    moto = pytest.importorskip('moto', reason='moto is not installed (pip install "moto[s3,sqs]")')
    pytest.importorskip('boto3', reason='boto3 is not installed')
    for k, v in {'AWS_ACCESS_KEY_ID': 'testing', 'AWS_SECRET_ACCESS_KEY': 'testing',
                 'AWS_DEFAULT_REGION': 'us-east-1'}.items():
        monkeypatch.setenv(k, v)
    mock = getattr(moto, 'mock_aws', None)
    if mock is None:
        pytest.skip('moto < 5 (no mock_aws)')
    with mock():
        yield


def test_s3_contract_and_sqs_events_under_moto(moto_aws, tmp_path):
    import boto3
    from sajha.core import storage_events as se
    from sajha.core.storage import S3SyncManager, S3StorageBackend
    boto3.client('s3', region_name='us-east-1').create_bucket(Bucket='sajha-test')
    b = S3StorageBackend('sajha-test', prefix='sajha', cache_dir=str(tmp_path))
    _contract(b)

    sqs = boto3.client('sqs', region_name='us-east-1')
    url = sqs.create_queue(QueueName='sajha-events')['QueueUrl']
    b.write_text('config/tools/c.json', '{}')
    sqs.send_message(QueueUrl=url, MessageBody=json.dumps({'Records': [
        {'eventName': 'ObjectCreated:Put', 's3': {'bucket': {'name': 'sajha-test'},
                                                   'object': {'key': 'sajha/config/tools/c.json'}}}]}))
    sync = S3SyncManager(b, interval=3600)
    calls = []
    sync.watch('config/tools', lambda: calls.append('tools'))
    ev = se.StorageEvents(b, se.SqsSource(sqs, url, wait_seconds=0), sync, relay=False)
    assert ev.poll_once() == 1 and calls == ['tools']
    assert sqs.receive_message(QueueUrl=url, WaitTimeSeconds=0).get('Messages') is None    # acknowledged


@pytest.mark.skipif(not os.environ.get('SAJHA_TEST_S3_ENDPOINT'), reason='SAJHA_TEST_S3_ENDPOINT not set (MinIO)')
def test_s3_contract_on_minio(tmp_path):
    boto3 = pytest.importorskip('boto3')
    from sajha.core.storage import S3StorageBackend
    endpoint = os.environ['SAJHA_TEST_S3_ENDPOINT']
    name = f'sajha-{uuid.uuid4().hex[:8]}'
    boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1').create_bucket(Bucket=name)
    _contract(S3StorageBackend(name, prefix='sajha', cache_dir=str(tmp_path), endpoint_url=endpoint))


@pytest.mark.skipif(not os.environ.get('SAJHA_TEST_AZURITE'), reason='SAJHA_TEST_AZURITE not set (Azurite)')
def test_azure_contract_on_azurite(tmp_path):
    blob = pytest.importorskip('azure.storage.blob')
    from sajha.core.storage import AzureBlobStorageBackend
    conn = os.environ['SAJHA_TEST_AZURITE']
    name = f'sajha-{uuid.uuid4().hex[:8]}'
    blob.BlobServiceClient.from_connection_string(conn).create_container(name)
    _contract(AzureBlobStorageBackend(name, connection_string=conn, prefix='sajha', cache_dir=str(tmp_path)))


@pytest.mark.skipif(not os.environ.get('STORAGE_EMULATOR_HOST'), reason='STORAGE_EMULATOR_HOST not set (fake-gcs-server)')
def test_gcs_contract_on_fake_gcs_server(tmp_path):
    gcs = pytest.importorskip('google.cloud.storage')
    from sajha.core.storage import GCSStorageBackend
    name = f'sajha-{uuid.uuid4().hex[:8]}'
    gcs.Client(project='test').create_bucket(name)
    _contract(GCSStorageBackend(name, project='test', prefix='sajha', cache_dir=str(tmp_path)))

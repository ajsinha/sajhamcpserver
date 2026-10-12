# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Data Connectors: the Weaviate and Chroma adapters (sajha/connectors/vector_weaviate.py,
vector_chroma.py) against in-process HTTP fakes: listing with the allowlist, describing, the
search request SAJHA writes (nearVector / bm25 GraphQL for Weaviate, a query with a where filter
for Chroma), filters checked against the schema, masking of text and metadata, hidden fields left
out, secrets never echoed, and the generated tools through the service. No SDK is needed."""

from __future__ import annotations

import json
import types

import httpx
import pytest

from sajha.connectors import catalog, model, pool, service, store, vector
from sajha.connectors.drivers import ConnectorError
from sajha.connectors.vector_chroma import ChromaAdapter
from sajha.connectors.vector_weaviate import WeaviateAdapter
from tests.test_connectors import FakeRegistry, _run


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    store.forget()
    catalog.invalidate()
    pool.clear()
    yield tmp_path
    store.forget()
    catalog.invalidate()
    pool.clear()


class Fake:
    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, request):
        self.seen.append(request)
        key = (request.method, request.url.path)
        answer = self.routes.get(key)
        if answer is None:
            return httpx.Response(404, text='no such route')
        return answer(request) if callable(answer) else answer

    def body(self, i=-1):
        return json.loads(self.seen[i].content)


@pytest.fixture
def fake():
    holder = {}

    def install(routes):
        holder['f'] = Fake(routes)
        vector.set_transport(httpx.MockTransport(holder['f']))
        return holder['f']
    yield install
    vector.set_transport(None)


def embedder(monkeypatch, vec=(0.25, 0.5, 0.75)):
    from sajha.ai.llm import factory as fac
    calls = []

    def model_(name, kind=''):
        def embeddings_create(input=None, sajha=None):
            calls.append((input, name))
            return types.SimpleNamespace(vectors=[list(vec)])
        return types.SimpleNamespace(embeddings_create=embeddings_create)
    monkeypatch.setattr(fac, '_factory', types.SimpleNamespace(model=model_))
    return calls


# ── Weaviate ────────────────────────────────────────────────────────────

SCHEMA = {'classes': [{'class': 'Article'}, {'class': 'Private'}]}
ARTICLE = {'class': 'Article', 'vectorizer': 'none', 'properties': [
    {'name': 'text', 'dataType': ['text']}, {'name': 'title', 'dataType': ['text']},
    {'name': 'year', 'dataType': ['int']}, {'name': 'email', 'dataType': ['text']},
    {'name': 'ssn', 'dataType': ['text']}, {'name': 'author', 'dataType': ['Person']}]}


def weaviate_routes(answer=None):
    hits = answer or {'data': {'Get': {'Article': [
        {'text': 'hello world', 'title': 'Doc', 'year': 2024, 'email': 'ann@example.com',
         '_additional': {'id': 'u-1', 'distance': 0.125, 'score': None}}]}}}
    return {('GET', '/v1/meta'): httpx.Response(200, json={'version': '1.25.3'}),
            ('GET', '/v1/schema'): httpx.Response(200, json=SCHEMA),
            ('GET', '/v1/schema/Article'): httpx.Response(200, json=ARTICLE),
            ('POST', '/v1/graphql'): httpx.Response(200, json=hits)}


def weaviate_conn(**kw):
    rec = {'id': 'wv', 'kind': 'weaviate', 'options': {'url': 'http://weaviate.local:8080'},
           'allow': {'deny_tables': ['Private']},
           'masking': [{'column': 'email', 'mode': 'redact'}, {'column': 'ssn', 'mode': 'hide'}]}
    rec.update(kw)
    return model.parse(rec)


def test_weaviate_tools_list_describe_and_search_with_masking(storage_dir, fake, monkeypatch):
    monkeypatch.setenv('WVK', 'weaviate-secret-key')
    f = fake(weaviate_routes())
    reg = FakeRegistry()
    out = service.save({'id': 'wv', 'kind': 'weaviate', 'options': {'url': 'http://weaviate.local:8080'},
                        'secrets': {'api_key': 'env:WVK'}, 'allow': {'deny_tables': ['Private']},
                        'masking': [{'column': 'email', 'mode': 'redact'}, {'column': 'ssn', 'mode': 'hide'}]}, reg)
    assert sorted(out['tools']) == ['wv__describe_collection', 'wv__list_collections', 'wv__search']
    assert _run(reg, 'wv__list_collections', {})['collections'] == [{'name': 'Article', 'type': 'collection'}]
    desc = _run(reg, 'wv__describe_collection', {})
    assert desc['fields'] == {'text': 'text', 'title': 'text', 'year': 'int', 'email': 'text'}
    assert desc['hidden_fields'] == ['ssn']
    res = _run(reg, 'wv__search', {'vector': [0.1, 0.2, 0.3], 'top_k': 3, 'filters': {'title': 'Doc', 'year': 2024}})
    assert res['results'] == [{'id': 'u-1', 'score': 0.875, 'text': 'hello world',
                               'metadata': {'title': 'Doc', 'year': 2024, 'email': '[REDACTED]'}}]
    q = f.body()['query']
    assert q == ('{ Get { Article(limit: 3, nearVector: {vector: [0.1,0.2,0.3]}, where: {operator: And, operands: '
                 '[{path: ["title"], operator: Equal, valueText: "Doc"}, {path: ["year"], operator: Equal, '
                 'valueInt: 2024}]}) { text title year email _additional { id distance score } } } }')
    assert 'ssn' not in q and 'author' not in q                         # hidden and cross-reference left out
    assert f.seen[-1].headers['authorization'] == 'Bearer weaviate-secret-key'
    with pytest.raises(ConnectorError, match='not available'):
        _run(reg, 'wv__search', {'vector': [1.0], 'collection': 'Private'})


def test_weaviate_embeds_the_query_and_targets_a_named_vector(storage_dir, fake, monkeypatch):
    calls = embedder(monkeypatch)
    f = fake(weaviate_routes())
    conn = weaviate_conn(vector={'embedding_model': 'embedding', 'vector_name': 'body'})
    vector.search(conn, {'query': 'greeting'})
    assert calls == [(['greeting'], 'embedding')]
    assert 'nearVector: {vector: [0.25,0.5,0.75], targetVectors: ["body"]}' in f.body()['query']


def test_weaviate_keyword_search_when_embedding_is_none(storage_dir, fake, monkeypatch):
    f = fake(weaviate_routes({'data': {'Get': {'Article': [
        {'text': 't', 'title': 'x', '_additional': {'id': 'u-2', 'distance': None, 'score': '0.75'}}]}}}))
    conn = weaviate_conn(vector={'embedding_model': 'none'})
    out = vector.search(conn, {'query': 'he said "hi" \\ bye', 'filters': {'title': 'a"b'}})
    assert out['results'][0]['score'] == 0.75
    q = f.body()['query']
    assert 'bm25: {query: "he said \\"hi\\" \\\\ bye"}' in q and 'valueText: "a\\"b"' in q


def test_weaviate_filters_are_checked_against_the_schema(storage_dir, fake):
    fake(weaviate_routes())
    conn = weaviate_conn()
    for bad, msg in (({'nope': 1}, 'not a property'), ({'year': 'x'}, 'whole number'),
                     ({'year': True}, 'whole number'), ({'email': 'a'}, 'masked'), ({'ssn': 'a'}, 'masked')):
        with pytest.raises(ConnectorError, match=msg):
            vector.search(conn, {'vector': [1.0], 'filters': bad})


def test_weaviate_errors_are_reported_without_the_key(storage_dir, fake, monkeypatch):
    monkeypatch.setenv('WVK', 'weaviate-secret-key')
    routes = weaviate_routes({'errors': [{'message': 'nearVector: vector lengths do not match'}]})
    fake(routes)
    conn = weaviate_conn(secrets={'api_key': 'env:WVK'})
    with pytest.raises(ConnectorError, match='vector lengths') as e:
        vector.search(conn, {'vector': [1.0]})
    assert 'weaviate-secret-key' not in str(e.value)
    routes[('POST', '/v1/graphql')] = httpx.Response(500, text='boom weaviate-secret-key')
    with pytest.raises(ConnectorError) as e:
        vector.search(conn, {'vector': [1.0]})
    assert 'weaviate-secret-key' not in str(e.value)
    assert vector.test(conn)['server_version'] == 'Weaviate 1.25.3'


# ── Chroma ──────────────────────────────────────────────────────────────

V2 = '/api/v2/tenants/acme/databases/kb'


def chroma_routes(base=V2):
    return {('GET', '/api/v2/version'): httpx.Response(200, json='1.0.12'),
            ('GET', '/api/v1/version'): httpx.Response(200, json='0.5.23'),
            ('GET', f'{base}/collections'): httpx.Response(200, json=[{'name': 'docs', 'id': 'c-1'},
                                                                       {'name': 'secret', 'id': 'c-2'}]),
            ('GET', f'{base}/collections/docs'): httpx.Response(200, json={'name': 'docs', 'id': 'c-1', 'dimension': 3}),
            ('GET', f'{base}/collections/c-1/count'): httpx.Response(200, json=2),
            ('POST', f'{base}/collections/c-1/get'): httpx.Response(200, json={'metadatas': [
                {'lang': 'en', 'email': 'a@b.c'}, {'lang': 'fr', 'page': 3}]}),
            ('POST', f'{base}/collections/c-1/query'): httpx.Response(200, json={
                'ids': [['r1', 'r2']], 'documents': [['refund policy text', 'other']],
                'metadatas': [[{'lang': 'en', 'email': 'ann@example.com'}, None]], 'distances': [[0.2, 0.5]]})}


def chroma_conn(**kw):
    rec = {'id': 'ch', 'kind': 'chroma', 'options': {'url': 'http://chroma.local:8000', 'tenant': 'acme',
                                                     'database': 'kb'},
           'allow': {'deny_tables': ['secret']}, 'masking': [{'column': 'email', 'mode': 'partial'}]}
    rec.update(kw)
    return model.parse(rec)


def test_chroma_tools_list_describe_and_search(storage_dir, fake, monkeypatch):
    monkeypatch.setenv('CHK', 'chroma-token')
    f = fake(chroma_routes())
    reg = FakeRegistry()
    out = service.save({'id': 'ch', 'kind': 'chroma', 'options': {'url': 'http://chroma.local:8000', 'tenant': 'acme',
                                                                  'database': 'kb'},
                        'secrets': {'api_key': 'env:CHK'}, 'allow': {'deny_tables': ['secret']},
                        'masking': [{'column': 'email', 'mode': 'hide'}]}, reg)
    assert sorted(out['tools']) == ['ch__describe_collection', 'ch__list_collections', 'ch__search']
    assert _run(reg, 'ch__list_collections', {})['collections'] == [{'name': 'docs', 'type': 'collection'}]
    desc = _run(reg, 'ch__describe_collection', {})
    assert desc['points'] == 2 and desc['dimension'] == 3 and desc['fields'] == {'lang': 'str', 'page': 'int'}
    assert desc['hidden_fields'] == ['email']
    res = _run(reg, 'ch__search', {'vector': [0.1, 0.2, 0.3], 'top_k': 2, 'filters': {'lang': 'en'}})
    assert res['results'] == [{'id': 'r1', 'score': 0.8, 'text': 'refund policy text', 'metadata': {'lang': 'en'}},
                              {'id': 'r2', 'score': 0.5, 'text': 'other', 'metadata': {}}]
    assert f.body() == {'query_embeddings': [[0.1, 0.2, 0.3]], 'n_results': 2,
                        'include': ['documents', 'metadatas', 'distances'], 'where': {'lang': {'$eq': 'en'}}}
    assert f.seen[-1].headers['x-chroma-token'] == 'chroma-token'


def test_chroma_embeds_text_joins_filters_and_masks(storage_dir, fake, monkeypatch):
    calls = embedder(monkeypatch)
    f = fake(chroma_routes())
    conn = chroma_conn(vector={'distance': 'l2'})
    out = vector.search(conn, {'query': 'refunds', 'filters': {'lang': 'en', 'page': 3}})
    assert calls == [(['refunds'], 'embedding')]
    body = f.body()
    assert body['query_embeddings'] == [[0.25, 0.5, 0.75]]
    assert body['where'] == {'$and': [{'lang': {'$eq': 'en'}}, {'page': {'$eq': 3}}]}
    assert out['results'][0]['score'] == -0.2
    assert out['results'][0]['metadata']['email'] != 'ann@example.com'          # partial mask


def test_chroma_v1_api_and_bearer_auth(storage_dir, fake, monkeypatch):
    monkeypatch.setenv('CHK', 'chroma-token')
    f = fake(chroma_routes('/api/v1'))
    conn = chroma_conn(options={'url': 'http://chroma.local:8000', 'api_version': 'v1', 'auth_header': 'authorization'},
                       secrets={'api_key': 'env:CHK'})
    assert vector.test(conn)['server_version'] == 'Chroma 0.5.23'
    vector.search(conn, {'vector': [1.0, 0.0, 0.0]})
    assert f.seen[-1].url.path == '/api/v1/collections/c-1/query'
    assert f.seen[-1].headers['authorization'] == 'Bearer chroma-token'
    bad = chroma_conn(options={'url': 'http://c:8000', 'tenant': '../x'})
    with pytest.raises(ConnectorError, match='tenant'):
        vector.list_collections(bad, refresh=True)


def test_the_adapters_need_no_sdk_and_say_what_they_search():
    import sys
    assert 'weaviate' not in sys.modules and 'chromadb' not in sys.modules
    assert vector.ADAPTERS['weaviate'].__class__ is WeaviateAdapter
    assert vector.ADAPTERS['chroma'].__class__ is ChromaAdapter
    assert model.KINDS['weaviate'] == model.KINDS['chroma'] == 'search'
    w, c = weaviate_conn(), chroma_conn()
    assert WeaviateAdapter().needs_vector(w) and ChromaAdapter().needs_vector(c)
    assert not WeaviateAdapter().needs_vector(weaviate_conn(vector={'embedding_model': 'none'}))
    kinds = {k['kind']: k for k in service.kinds()} if hasattr(service, 'kinds') else {}
    if kinds:
        assert kinds['weaviate']['name'] == 'Weaviate' and kinds['chroma']['pip'] in ('', None)

"""
JSON Schemas (2020-12) of every ``/sajhanet/v1/`` message, copied from the protocol
specification: the shared definitions of §7.6 (``urn:sajha:net:v1``, extended with the record
definitions the later sections add to the same ``$defs``) and one schema per request and response.

``validate(name, value)`` raises :class:`SchemaError` with the first problem; ``errors`` lists them.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

S = 'https://json-schema.org/draft/2020-12/schema'
R = 'urn:sajha:net:v1#/$defs/'


def _ref(name: str) -> Dict[str, str]:
    return {'$ref': R + name}


def _updates() -> Dict[str, Any]:
    return {'type': 'array', 'maxItems': 32, 'items': _ref('member_entry')}


INSTANCE_NAME = {'type': 'string', 'maxLength': 47, 'anyOf': [
    {'pattern': '^[a-z][a-z0-9-]{0,30}[a-z0-9]$', 'not': {'pattern': '--'}},
    {'pattern': '^[0-9]{1,3}(\\.[0-9]{1,3}){3}:[0-9]{1,5}$'},
    {'pattern': '^\\[[0-9a-f:.]+\\]:[0-9]{1,5}$'}]}

TIMESTAMP = {'type': 'string', 'format': 'date-time', 'pattern': 'Z$'}
TS_OR_NULL = {'anyOf': [_ref('timestamp'), {'type': 'null'}]}

DEFS: Dict[str, Any] = {
    'net_name': {'type': 'string', 'pattern': '^(?!.*__)(?!.*_$)[a-z][a-z0-9_-]{0,15}$'},
    'contract_hash': {'type': 'string', 'pattern': '^sha-256:[A-Za-z0-9_-]{43}$'},
    'instance_name': INSTANCE_NAME,
    'timestamp': TIMESTAMP,
    'b64': {'type': 'string', 'contentEncoding': 'base64'},
    'b64url': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]+$'},
    'version': {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991},
    'cert_chain': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {'$ref': '#/$defs/b64'},
                   'description': 'DER X.509 certificates, leaf first, without the root'},
    'signature': {'type': 'object', 'required': ['alg', 'keyid', 'sig'], 'additionalProperties': False,
                  'properties': {'alg': {'enum': ['ed25519', 'ecdsa-p256-sha256']},
                                 'keyid': {'$ref': '#/$defs/b64url'}, 'sig': {'$ref': '#/$defs/b64url'}}},
    'extension': {'type': 'object', 'required': ['protocol_versions', 'endpoint'], 'properties': {
        'protocol_versions': {'type': 'array', 'minItems': 1, 'items': {'type': 'integer', 'minimum': 1}},
        'net': {'$ref': '#/$defs/net_name'},
        'instance': {'$ref': '#/$defs/instance_name'},
        'kind': {'enum': ['sajha', 'agent', 'sponsored']},
        'sponsor': {'$ref': '#/$defs/instance_name'},
        'endpoint': {'type': 'string', 'pattern': '^/.*/$'},
        'features': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'user_identity': {'type': 'array', 'items': {'enum': ['api_key', 'assertion', 'token_exchange', 'none']}},
        'signature_algorithms': {'type': 'array', 'items': {'enum': ['ed25519', 'ecdsa-p256-sha256']}}}},
    'digests': {'type': 'object', 'required': ['catalog', 'keys', 'blocks', 'revocations'], 'properties': {
        'catalog': {'type': 'string', 'maxLength': 128},
        'keys': {'$ref': '#/$defs/version'}, 'blocks': {'$ref': '#/$defs/version'},
        'revocations': {'$ref': '#/$defs/version'}, 'conflicts': {'$ref': '#/$defs/version'}}},
    'member_record': {'type': 'object', 'required': [
        'type', 'net', 'name', 'url', 'mcp_path', 'kind', 'protocol_versions', 'features', 'user_identity',
        'incarnation', 'seq', 'digests', 'leaving', 'issued_at'], 'properties': {
        'type': {'const': 'member'}, 'net': {'$ref': '#/$defs/net_name'}, 'name': {'$ref': '#/$defs/instance_name'},
        'url': {'type': 'string', 'format': 'uri', 'pattern': '^https?://[^/?#]+(/[^?#]*[^/?#])?$'},
        'mcp_path': {'type': 'string', 'pattern': '^/'}, 'region': {'type': 'string', 'maxLength': 64},
        'labels': {'type': 'object', 'maxProperties': 32, 'additionalProperties': {'type': 'string', 'maxLength': 128}},
        'kind': {'enum': ['sajha', 'agent', 'sponsored']},
        'sponsor': {'$ref': '#/$defs/instance_name'},
        'protocol_versions': {'type': 'array', 'minItems': 1, 'items': {'type': 'integer', 'minimum': 1}},
        'features': {'type': 'array', 'items': {'type': 'string'}, 'uniqueItems': True},
        'user_identity': {'type': 'array', 'items': {'type': 'string'}},
        'incarnation': {'$ref': '#/$defs/version'}, 'seq': {'$ref': '#/$defs/version'},
        'digests': {'$ref': '#/$defs/digests'}, 'leaving': {'type': 'boolean'},
        'issued_at': {'$ref': '#/$defs/timestamp'}}},
    'member_entry': {'type': 'object', 'required': ['record', 'signature', 'state'], 'properties': {
        'record': {'$ref': '#/$defs/member_record'}, 'signature': {'$ref': '#/$defs/signature'},
        'certificate': {'$ref': '#/$defs/cert_chain'}, 'state': {'enum': ['alive', 'suspect', 'dead', 'left']},
        'reported_by': {'$ref': '#/$defs/instance_name'}, 'reported_at': {'$ref': '#/$defs/timestamp'}}},
    'problem': {'type': 'object', 'required': ['type', 'status', 'reason'], 'properties': {
        'type': {'type': 'string', 'pattern': '^urn:sajha:net:error:[a-z_]+$'}, 'title': {'type': 'string'},
        'status': {'type': 'integer'}, 'reason': {'type': 'string', 'pattern': '^[a-z_]+$'},
        'detail': {'type': 'string', 'maxLength': 1024},
        'supported_versions': {'type': 'array', 'items': {'type': 'integer'}}}},
    # §11.1
    'key_record': {'type': 'object', 'required': [
        'type', 'net', 'key_id', 'key_prefix', 'name', 'key_hash', 'home_instance', 'owner', 'enabled', 'expires_at',
        'revoked_at', 'tool_access_mode', 'tool_access_list', 'persistent', 'version', 'updated_at', 'signature'],
        'properties': {
            'type': {'const': 'key'}, 'net': {'$ref': '#/$defs/net_name'},
            'key_id': {'type': 'string', 'maxLength': 64}, 'key_prefix': {'type': 'string', 'maxLength': 16},
            'name': {'type': 'string', 'maxLength': 255}, 'key_hash': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
            'home_instance': {'$ref': '#/$defs/instance_name'},
            'owner': {'type': 'object', 'required': ['user_id', 'user_name', 'roles'], 'properties': {
                'user_id': {'type': 'string'}, 'user_name': {'type': 'string'}, 'display_name': {'type': 'string'},
                'roles': {'type': 'array', 'items': {'type': 'string'}}}},
            'enabled': {'type': 'boolean'},
            'expires_at': {'anyOf': [{'$ref': '#/$defs/timestamp'}, {'type': 'null'}]},
            'revoked_at': {'anyOf': [{'$ref': '#/$defs/timestamp'}, {'type': 'null'}]},
            'tool_access_mode': {'enum': ['all', 'allowlist', 'denylist', 'regex']},
            'tool_access_list': {'type': 'array', 'items': {'type': 'string'}},
            'persistent': {'type': 'boolean'}, 'version': {'$ref': '#/$defs/version'},
            'updated_at': {'$ref': '#/$defs/timestamp'}, 'signature': {'$ref': '#/$defs/signature'}}},
    # §12
    'blocks_document': {'type': 'object', 'required': ['type', 'net', 'instance', 'version', 'blocks', 'signature'],
                        'properties': {
        'type': {'const': 'blocks'}, 'net': {'$ref': '#/$defs/net_name'},
        'instance': {'$ref': '#/$defs/instance_name'}, 'version': {'$ref': '#/$defs/version'},
        'blocks': {'type': 'array', 'maxItems': 1000, 'items': {
            'type': 'object', 'required': ['id', 'level', 'target_instance', 'set_at'], 'properties': {
                'id': {'type': 'string'}, 'level': {'enum': ['instance', 'inbound', 'outbound', 'tool', 'user']},
                'target_instance': {'anyOf': [{'$ref': '#/$defs/instance_name'}, {'const': '*'}]},
                'tool': {'type': 'string'}, 'user': {'type': 'string'},
                'reason': {'type': 'string', 'maxLength': 500}, 'set_at': {'$ref': '#/$defs/timestamp'},
                'expires_at': {'$ref': '#/$defs/timestamp'}}}},
        'signature': {'$ref': '#/$defs/signature'}}},
    # §10.7
    'conflicts_document': {'type': 'object', 'required': ['type', 'net', 'instance', 'version', 'conflicts',
                                                          'signature'], 'properties': {
        'type': {'const': 'conflicts'}, 'net': {'$ref': '#/$defs/net_name'},
        'instance': {'$ref': '#/$defs/instance_name'}, 'version': {'$ref': '#/$defs/version'},
        'conflicts': {'type': 'array', 'maxItems': 1000, 'items': {
            'type': 'object', 'required': ['tool', 'offers', 'since'], 'properties': {
                'tool': {'type': 'string'},
                'offers': {'type': 'array', 'minItems': 2, 'items': {
                    'type': 'object', 'required': ['instance', 'contract_hash'], 'properties': {
                        'instance': {'$ref': '#/$defs/instance_name'},
                        'contract_hash': {'$ref': '#/$defs/contract_hash'}}}},
                'since': {'$ref': '#/$defs/timestamp'}}}},
        'signature': {'$ref': '#/$defs/signature'}}},
    # §13
    'revocation_list': {'type': 'object', 'required': ['type', 'net', 'version', 'issued_at', 'revoked', 'signature'],
                        'properties': {
        'type': {'const': 'revocations'}, 'net': {'$ref': '#/$defs/net_name'},
        'version': {'$ref': '#/$defs/version'}, 'issued_at': {'$ref': '#/$defs/timestamp'},
        'revoked': {'type': 'array', 'items': {
            'type': 'object', 'required': ['revoked_at'],
            'anyOf': [{'required': ['instance']}, {'required': ['serial']}], 'properties': {
                'instance': {'$ref': '#/$defs/instance_name'}, 'serial': {'type': 'string', 'pattern': '^[0-9a-f]+$'},
                'revoked_at': {'$ref': '#/$defs/timestamp'}, 'reason': {'type': 'string', 'maxLength': 200}}}},
        'signature': {'$ref': '#/$defs/signature'}}},
    # §15.5
    'user_assertion': {'type': 'object', 'required': ['type', 'net', 'iss', 'user', 'key_id', 'aud', 'iat', 'exp',
                                                      'jti', 'trace_id', 'signature'], 'properties': {
        'type': {'const': 'assertion'}, 'net': {'$ref': '#/$defs/net_name'},
        'iss': {'$ref': '#/$defs/instance_name'}, 'user': {'type': 'string'}, 'key_id': {'type': 'string'},
        'aud': {'$ref': '#/$defs/instance_name'}, 'iat': {'type': 'integer'}, 'exp': {'type': 'integer'},
        'jti': {'type': 'string', 'minLength': 16}, 'trace_id': {'type': 'string', 'pattern': '^[0-9a-f]{32}$'},
        'signature': {'$ref': '#/$defs/signature'}}},
}

SHARED = {'$schema': S, '$id': 'urn:sajha:net:v1', '$defs': DEFS}

TOOL_NET_META = {'type': 'object', 'required': ['net', 'instance', 'contract_hash'], 'properties': {
    'net': _ref('net_name'), 'instance': _ref('instance_name'), 'region': {'type': 'string'},
    'labels': {'type': 'object', 'additionalProperties': {'type': 'string'}}, 'version': {'type': 'string'},
    'deprecated': {'type': 'boolean'},
    'data_classes': {'type': 'object', 'properties': {
        'arguments': {'type': 'array', 'items': {'type': 'string'}},
        'results': {'type': 'array', 'items': {'type': 'string'}}}},
    'llm_tool': {'type': 'boolean'}, 'latency_ms_p50': {'type': 'integer', 'minimum': 0},
    'health': {'enum': ['ok', 'degraded', 'down']}, 'per_user_results': {'type': 'boolean'},
    'contract_hash': _ref('contract_hash'), 'description_hash': {'type': 'string'}, 'origin': _ref('instance_name')}}


def _obj(required: List[str], props: Dict[str, Any], **extra) -> Dict[str, Any]:
    out = {'$schema': S, 'type': 'object', 'required': required, 'properties': props}
    out.update(extra)
    return out


MESSAGES: Dict[str, Dict[str, Any]] = {
    # §9.5
    'ping': _obj(['type', 'seq', 'updates'], {'type': {'const': 'ping'}, 'seq': {'type': 'integer', 'minimum': 0},
                                              'updates': _updates()}),
    'ack': _obj(['type', 'seq', 'updates'], {'type': {'const': 'ack'}, 'seq': {'type': 'integer', 'minimum': 0},
                                             'target': _ref('instance_name'), 'reachable': {'type': 'boolean'},
                                             'updates': _updates()}),
    'ping_req': _obj(['type', 'seq', 'target', 'updates'], {
        'type': {'const': 'ping-req'}, 'seq': {'type': 'integer', 'minimum': 0}, 'target': _ref('instance_name'),
        'updates': _updates()}),
    # §9.7
    'sync': _obj(['type', 'members'], {
        'type': {'const': 'sync'}, 'reason': {'enum': ['join', 'anti_entropy', 'certificate', 'rejoin']},
        'members': {'type': 'array', 'maxItems': 1024,
                    'items': {'allOf': [_ref('member_entry'), {'required': ['certificate']}]}}}),
    # §9.8
    'leave': _obj(['type', 'entry'], {'type': {'const': 'leave'}, 'entry': {'allOf': [
        _ref('member_entry'), {'required': ['certificate'], 'properties': {
            'state': {'const': 'left'}, 'record': {'properties': {'leaving': {'const': True}}}}}]}}),
    'leave_response': {'$schema': S, 'type': 'object'},
    # §10.2
    'catalog_request': {'$schema': S, 'type': 'object',
                        'properties': {'if_none_match': {'type': 'string', 'maxLength': 128}}},
    'catalog_response': _obj(['net', 'instance', 'catalog_digest', 'hash', 'unchanged'], {
        'net': _ref('net_name'), 'instance': _ref('instance_name'),
        'catalog_digest': {'type': 'string', 'maxLength': 128},
        'hash': {'type': 'string', 'pattern': '^sha-256:[A-Za-z0-9_-]{43}$'}, 'generated_at': _ref('timestamp'),
        'unchanged': {'type': 'boolean'},
        'tools': {'type': 'array', 'items': {'type': 'object', 'required': ['name', 'inputSchema', '_meta'],
                                             'properties': {'_meta': {'type': 'object', 'required': ['io.sajha/net'],
                                                                      'properties': {'io.sajha/net': TOOL_NET_META}}}}}}),
    'tool_net_meta': dict(TOOL_NET_META, **{'$schema': S}),
    # §10.5
    'visibility_request': _obj(['key_ids'], {'key_ids': {'type': 'array', 'minItems': 1, 'maxItems': 100,
                                                         'items': {'type': 'string'}}}),
    'visibility_response': _obj(['visibility'], {'visibility': {'type': 'object', 'additionalProperties': {
        'type': 'object', 'properties': {'tools': {'type': 'array', 'items': {'type': 'string'}},
                                         'reason': {'type': 'string'}}}}}),
    # §11.3, §11.4
    'keys_request': _obj(['since'], {'since': _ref('version'),
                                     'limit': {'type': 'integer', 'minimum': 1, 'maximum': 1000}}),
    'keys_response': _obj(['home_instance', 'version', 'records', 'more'], {
        'home_instance': _ref('instance_name'), 'version': _ref('version'),
        'records': {'type': 'array', 'items': _ref('key_record')}, 'more': {'type': 'boolean'},
        'next_since': _ref('version')}),
    'keys_digest_request': {'$schema': S, 'type': 'object'},
    'keys_digest_response': _obj(['home_instance', 'version', 'count', 'root'], {
        'home_instance': _ref('instance_name'), 'version': _ref('version'), 'count': {'type': 'integer', 'minimum': 0},
        'root': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]{43}$'}}),
    'empty_request': {'$schema': S, 'type': 'object'},
    # §14
    'enroll_request': _obj(['net', 'instance', 'token', 'csr'], {
        'net': _ref('net_name'), 'instance': _ref('instance_name'),
        'token': {'type': 'string', 'minLength': 22, 'maxLength': 256}, 'csr': _ref('b64')}),
    'enroll_response': _obj(['certificate', 'ca_certificate', 'not_after'], {
        'certificate': _ref('cert_chain'), 'ca_certificate': _ref('b64'), 'not_after': _ref('timestamp')}),
    'renew_request': _obj(['csr'], {'csr': _ref('b64')}),
    # §15.9 (token_exchange, SAJHA): an RFC 8693 style exchange of a user assertion for a host-scoped token
    'token_request': _obj(['grant_type', 'subject_token', 'subject_token_type', 'audience'], {
        'grant_type': {'const': 'urn:ietf:params:oauth:grant-type:token-exchange'},
        'subject_token': {'type': 'string', 'minLength': 16, 'maxLength': 8192},
        'subject_token_type': {'const': 'urn:sajha:net:user-assertion'},
        'audience': _ref('instance_name')}),
    'token_response': _obj(['access_token', 'issued_token_type', 'token_type', 'expires_in'], {
        'access_token': {'type': 'string', 'minLength': 32, 'maxLength': 256},
        'issued_token_type': {'const': 'urn:ietf:params:oauth:token-type:access_token'},
        'token_type': {'const': 'N_A'}, 'expires_in': {'type': 'integer', 'minimum': 1, 'maximum': 3600}}),
}

#: record and shared definitions validated by name too
for _n in ('member_record', 'member_entry', 'problem', 'extension', 'key_record', 'blocks_document',
           'conflicts_document', 'revocation_list', 'user_assertion', 'signature', 'digests'):
    MESSAGES.setdefault(_n, {'$schema': S, '$ref': R + _n})


class SchemaError(ValueError):
    pass


@lru_cache(maxsize=None)
def _validator(name: str):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    registry = Registry().with_resource('urn:sajha:net:v1', Resource.from_contents(SHARED))
    return Draft202012Validator(MESSAGES[name], registry=registry)


def errors(name: str, value: Any) -> List[str]:
    if name not in MESSAGES:
        raise KeyError(f'no schema {name!r}')
    out = []
    for e in sorted(_validator(name).iter_errors(value), key=lambda e: list(e.path)):
        where = '/'.join(str(p) for p in e.path)
        out.append(f'{where or "(root)"}: {e.message}'[:300])
    return out


def validate(name: str, value: Any) -> None:
    errs = errors(name, value)
    if errs:
        raise SchemaError(errs[0])


def is_valid(name: str, value: Any) -> bool:
    return not errors(name, value)

"""
SAJHA Net: the protocol-only core.

This package implements the wire protocol of SAJHA Net (the ``io.sajha/net`` MCP extension) as
specified in docs/protocol/SAJHA Net Protocol.md; the design is docs/architecture/SAJHA Net.md.

The core modules import nothing from the rest of SAJHA (``tests/test_sajhanet_core_boundary.py``
enforces it), so the SAJHA Net agent and the reference library can be built from them:

* :mod:`sajha.net.names`       net names, instance and address names, safe prefixes, qualified names (§5)
* :mod:`sajha.net.jcs`         RFC 8785 canonical JSON (§8.10)
* :mod:`sajha.net.sfv`         the RFC 8941 structured fields the protocol uses
* :mod:`sajha.net.crypto`      keys, certificates, thumbprints, record signatures (§8.1, §8.2, §8.10)
* :mod:`sajha.net.httpsig`     RFC 9421 request and response signatures, RFC 9530 digests (§8.3-§8.9)
* :mod:`sajha.net.errors`      reasons, HTTP statuses and problem bodies (§7.4, §7.5, §17)
* :mod:`sajha.net.schemas`     JSON Schemas of every ``/sajhanet/v1/`` message (§7.6 and each section)
* :mod:`sajha.net.models`      the configuration and data models of a participant
* :mod:`sajha.net.plugins`     the plug-in interfaces of design §5.3 and their registry
* :mod:`sajha.net.membership`  SWIM membership: member table, merge rules, dissemination, gossip agent (§9)
* :mod:`sajha.net.ca`          the SAJHA Net CA: tokens, enrollment, renewal, revocation list (§13, §14)
* :mod:`sajha.net.node`        one participant's view of one net, and the endpoint handlers (§7, §9, §13, §14)
* :mod:`sajha.net.contract`    contract checks every plug-in implementation must pass

SAJHA's integration (configuration, state store, notices, metrics, audit, the routes in
``sajha/routes/sajhanet_routes.py``) is :mod:`sajha.net.integration`, which depends on the core and
never the other way round.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

PROTOCOL_VERSION = 1
SUPPORTED_VERSIONS = (1,)
EXTENSION_ID = 'io.sajha/net'
ENDPOINT = '/sajhanet/v1/'
SIGNATURE_LABEL = 'sajhanet'
SIGNATURE_TAG = 'sajha-net-v1'

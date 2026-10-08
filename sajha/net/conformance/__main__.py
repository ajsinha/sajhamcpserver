"""
``python -m sajha.net.conformance``: run the SAJHA Net conformance suite (protocol §20) against a
participant, or against this process's protocol core (``--target library``). Exit status 1 when a
case fails. Guide: docs/clients/SAJHA Net Agent.md ("Conformance").

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog='python -m sajha.net.conformance',
                                description='Run the SAJHA Net conformance suite (protocol §20).')
    p.add_argument('--target', required=True, help='the participant\'s base URL, or "library" for target L')
    p.add_argument('--net', default='', help='the net to test in (required for a URL target)')
    p.add_argument('--instance', default='', help='the target\'s instance name (needed for a sponsored participant, '
                                                  'which shares its sponsor\'s URL)')
    p.add_argument('--mcp-path', default='', help='the target\'s MCP path (default: from its member record)')
    p.add_argument('--name', default='', help='the runner\'s own instance name (default conformance-<random>)')
    p.add_argument('--identity-dir', default='', help='keep (and reuse) the runner\'s key and certificate here')
    p.add_argument('--ca-url', default='', help='enroll the runner at this CA participant (builtin_ca nets)')
    p.add_argument('--token', default='', help='the enrollment token for --ca-url')
    p.add_argument('--ca-cert', default='', help='the net\'s CA certificate (PEM), to verify the target')
    p.add_argument('--api-key', default='', help='CALL-01: a key of a user the target accepts')
    p.add_argument('--tool', default='', help='a tool the target offers (default: the first in its catalog)')
    p.add_argument('--only', action='append', default=[], help='case ids to run (repeatable or comma separated)')
    p.add_argument('--allow-plain-http', action='store_true', help='lab use: enroll over plain HTTP')
    p.add_argument('--insecure', action='store_true', help='do not verify the target\'s TLS certificate')
    p.add_argument('--json', action='store_true', help='print the report as JSON')
    a = p.parse_args(argv)
    from sajha.net import conformance as C
    ids = [x.strip() for v in a.only for x in v.split(',') if x.strip()] or None
    if a.target == 'library':
        rep = C.run_library(ids)
    else:
        if not a.net:
            p.error('--net is required for a URL target')
        from sajha.net import crypto, httpsig
        from sajha.net.library import IdentityFiles, enroll, self_signed
        from sajha.net.plugins import create
        from sajha.net.trust import CATrust, FirstUseTrust
        connector = create('connector', 'sajha_native', verify_tls=not a.insecure)
        files = IdentityFiles(a.identity_dir) if a.identity_dir else None
        held = files.load() if files else None
        ca_cert = None
        if a.ca_cert:
            with open(a.ca_cert, 'rb') as f:
                ca_cert = crypto.load_cert(f.read())
        elif files is not None:
            ca_cert = files.ca_certificate()
        if held is not None:
            key, cert = held
        else:
            name = a.name or f'conformance-{secrets.token_hex(3)}'
            if a.ca_url and a.token:
                key, cert, ca_cert = enroll(connector, a.net, name, 'conformance.invalid', a.ca_url, a.token,
                                            require_https=not a.allow_plain_http, ca_certificate=ca_cert)
            else:
                key, cert = self_signed(a.net, name, 'conformance.invalid')
            if files is not None:
                files.save(key, cert, ca_cert)
        if ca_cert is not None and not (cert.issuer == cert.subject):
            trust = CATrust(a.net, ca_cert, lambda: None)
        else:
            mem = {}
            trust = FirstUseTrust(a.net, lambda: mem, mem.__setitem__)
        rep = C.run(a.target.rstrip('/'), a.net, connector=connector, signer=httpsig.Signer(key, [cert]), trust=trust,
                    instance=a.instance, mcp_path=a.mcp_path, api_key=a.api_key, tool=a.tool, ids=ids)
    print(json.dumps(rep.to_dict(), indent=1) if a.json else rep.text())
    return 1 if rep.failed() else 0


if __name__ == '__main__':
    sys.exit(main())

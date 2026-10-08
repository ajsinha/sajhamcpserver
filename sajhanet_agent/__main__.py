"""
``python -m sajhanet_agent``: front one MCP server as a SAJHA Net participant. See
docs/clients/SAJHA Net Agent.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from urllib.parse import urlsplit


def _pairs(items, what):
    out = {}
    for item in items or []:
        k, sep, v = item.partition('=' if what == 'label' else ':')
        if not sep or not k.strip():
            raise SystemExit(f'--{what} takes {"key=value" if what == "label" else "Name: value"}, not {item!r}')
        out[k.strip()] = v.strip()
    return out


def _list(values):
    out = []
    for v in values or []:
        out.extend(x.strip() for x in v.split(',') if x.strip())
    return out


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='python -m sajhanet_agent',
                                description='Front an MCP server (stdio or HTTP) as a SAJHA Net participant.')
    p.add_argument('--net', required=True, help='the net to join (protocol §5.1)')
    p.add_argument('--instance', required=True, help='this participant\'s instance name in the net (§5.2)')
    p.add_argument('--url', required=True, help='the base URL peers reach this agent at, e.g. https://host:8790')
    p.add_argument('--listen', default='', help='host:port to listen on (default: 0.0.0.0 and the port of --url)')
    p.add_argument('--seed', action='append', default=[], help='a member to join through (repeatable)')
    p.add_argument('--founder', action='store_true', help='start the net if no seed answers')
    mcp = p.add_mutually_exclusive_group(required=True)
    mcp.add_argument('--mcp-command', help='the MCP server to run over stdio, e.g. "python server.py"')
    mcp.add_argument('--mcp-url', help='the MCP server\'s Streamable HTTP endpoint')
    p.add_argument('--mcp-header', action='append', default=[], help='"Name: value" sent to an --mcp-url server')
    p.add_argument('--admission', choices=('open', 'builtin_ca', 'manual'), default='open',
                   help='open: self-signed, accepted on first use (default); builtin_ca: a certificate from the '
                        'net\'s CA (give --ca-url and --token once); manual: self-signed, pinned by peers')
    p.add_argument('--ca-url', default='', help='builtin_ca: the CA participant\'s base URL')
    p.add_argument('--token', default='', help='builtin_ca: the enrollment token (spent on first start)')
    p.add_argument('--pin', action='append', default=[], help='manual: a peer certificate thumbprint to trust')
    p.add_argument('--data-dir', default='data/sajhanet-agent', help='where the key, certificate and peer list live')
    p.add_argument('--export-tools', action='append', default=[], help='tool globs offered (default: all)')
    p.add_argument('--export-peers', action='append', default=[], help='peer instance globs served (default: all)')
    p.add_argument('--export-roles', action='append', default=[],
                   help='serve only users with one of these roles at their home (default: any)')
    p.add_argument('--service-calls', action='store_true', help='also serve calls that carry no user')
    p.add_argument('--no-key-verification', action='store_true',
                   help='keep no key directory and accept no forwarded API keys (service calls only)')
    p.add_argument('--region', default='')
    p.add_argument('--label', action='append', default=[], help='key=value label of this participant')
    p.add_argument('--allow-plain-http', action='store_true', help='lab use only: no HTTPS required')
    p.add_argument('--tls-cert', default='', help='serve HTTPS with this certificate (PEM)')
    p.add_argument('--tls-key', default='', help='the TLS certificate\'s key (PEM)')
    p.add_argument('--behind-tls-proxy', action='store_true', help='a TLS proxy terminates HTTPS in front of the agent')
    p.add_argument('--call-timeout', type=float, default=60.0)
    p.add_argument('--catalog-refresh', type=float, default=60.0, help='seconds between tools/list on the server')
    p.add_argument('--log-level', default='INFO')
    return p


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(a.log_level).upper(), logging.INFO),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    from sajhanet_agent.agent import Agent, AgentConfig
    from sajhanet_agent.server import make_server
    cfg = AgentConfig(net=a.net, instance=a.instance, url=a.url, seeds=list(a.seed), founder=a.founder,
                      admission=a.admission, ca_url=a.ca_url, token=a.token, pins=list(a.pin), data_dir=a.data_dir,
                      require_https=not a.allow_plain_http, region=a.region, labels=_pairs(a.label, 'label'),
                      export_tools=_list(a.export_tools) or ['*'], export_peers=_list(a.export_peers) or ['*'],
                      export_roles=_list(a.export_roles) or None, service_calls=a.service_calls,
                      verify_keys=not a.no_key_verification, mcp_command=a.mcp_command or '', mcp_url=a.mcp_url or '',
                      mcp_headers=_pairs(a.mcp_header, 'mcp-header'), call_timeout_seconds=a.call_timeout,
                      catalog_refresh_seconds=a.catalog_refresh)
    try:
        agent = Agent(cfg).start()
    except Exception as e:
        print(f'sajhanet-agent: {e}', file=sys.stderr)
        return 2
    u = urlsplit(a.url)
    host, _, port = (a.listen or f'0.0.0.0:{u.port or (443 if u.scheme == "https" else 80)}').rpartition(':')
    httpd = make_server(agent, host or '0.0.0.0', int(port), a.tls_cert, a.tls_key, a.behind_tls_proxy)
    agent.run_in_background()
    log = logging.getLogger('sajhanet_agent')
    st = agent.status()
    log.info(f'{st["instance"]} in {st["net"]} (kind agent, certificate {st["certificate"][:16]}...) on '
             f'{host or "0.0.0.0"}:{port}; offering {len(st["tools"])} tools')
    stop = threading.Event()

    def bye(*_):
        stop.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    try:
        httpd.serve_forever()
    finally:
        agent.stop(leave=True)
        log.info('left the net')
    return 0


if __name__ == '__main__':
    sys.exit(main())

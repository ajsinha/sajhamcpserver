# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Adversarial QA Plan 3.11 (outbound requests), P0: which outbound paths the SSRF guard covers, tested
with a corpus of internal addresses; the paths it does not cover are recorded as strict xfails (a
documented gap; the xfail turns into a failure the day a guard is added, so the record is updated).

Covered (``sajha.auth.oauth.clients.address_allowed``, resolved once and pinned): federation upstream
URLs (``sajha.federation.security.check_url``), OpenAPI/GraphQL import and its generated tools
(``sajha.api_import.fetch.guard``), OAuth CIMD fetches, async webhooks and alert webhooks; SAJHA Net peer
URLs have their own stricter rule (``check_peer_url``: loopback and link-local never, private only inside
``sajhanet.allowed_networks``).

Not covered (gaps, QA plan 3.11): the web crawler tools (``crawl_url`` and friends) fetch any URL the
caller names, cloud metadata included; Studio REST tools call the endpoint their author configured with
no address check.
"""

import ipaddress

import pytest

# The cloud metadata service, loopback, unspecified, private ranges, CGNAT and IPv6 forms that embed them.
INTERNAL = ['169.254.169.254', '127.0.0.1', '127.1.2.3', '0.0.0.0', '10.0.0.5', '172.16.3.4', '192.168.1.1',
            '100.64.0.1', '::1', 'fe80::1', 'fc00::1', '::ffff:169.254.169.254', '::ffff:127.0.0.1',
            '64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::1', '224.0.0.1']
INTERNAL_URLS = [f'http://{h}/latest/meta-data/' if ':' not in h else f'http://[{h}]/latest/meta-data/'
                 for h in INTERNAL] + ['http://localhost/admin', 'http://2130706433/', 'http://0x7f000001/']


@pytest.mark.parametrize('addr', INTERNAL)
def test_the_shared_address_rule_refuses_internal_addresses(addr):
    from sajha.auth.oauth.clients import address_allowed
    ip = ipaddress.ip_address(addr)
    assert not address_allowed(ip, addr)
    # allow_private never opens link-local (metadata), multicast or the unspecified address
    if addr in ('169.254.169.254', '::ffff:169.254.169.254', '64:ff9b::a9fe:a9fe', '2002:a9fe:a9fe::1',
                '0.0.0.0', '224.0.0.1', 'fe80::1'):
        assert not address_allowed(ip, addr, allow_private=True)


def test_the_shared_address_rule_allows_public_addresses():
    from sajha.auth.oauth.clients import address_allowed
    assert address_allowed(ipaddress.ip_address('93.184.216.34'), 'example.com')


class _Fed:
    allowed_hosts = []
    allow_localhost = False
    allow_private_networks = False


@pytest.mark.parametrize('url', INTERNAL_URLS)
def test_federation_upstream_urls_are_guarded(url):
    from sajha.federation.security import UnsafeURLError, check_url
    with pytest.raises(UnsafeURLError):
        check_url(url, _Fed())


@pytest.mark.parametrize('url', INTERNAL_URLS + ['file:///etc/passwd', 'gopher://127.0.0.1/', 'http://u:p@example.com/'])
def test_api_import_urls_are_guarded(url, monkeypatch):
    from sajha.api_import import fetch
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', 'false')
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_PRIVATE_NETWORKS', 'false')
    with pytest.raises(fetch.UnsafeURLError):
        fetch.guard(url)


@pytest.mark.parametrize('url', ['https://127.0.0.1/', 'https://169.254.169.254/', 'https://[::1]/',
                                 'https://10.0.0.5/', 'https://localhost/'])
def test_net_peer_urls_refuse_loopback_link_local_and_unlisted_private(url):
    from sajha.federation.security import UnsafeURLError, check_peer_url
    with pytest.raises(UnsafeURLError):
        check_peer_url(url, networks=[])


def test_net_peer_urls_never_allow_metadata_even_when_listed():
    from sajha.federation.security import UnsafeURLError, check_peer_url
    with pytest.raises(UnsafeURLError):
        check_peer_url('https://169.254.169.254/', networks=['169.254.0.0/16'])
    assert check_peer_url('https://10.0.0.5/', networks=['10.0.0.0/8'])[0] == '10.0.0.5'


@pytest.mark.xfail(strict=True, reason='documented gap (Adversarial QA Plan 3.11): the web crawler tools have no '
                                       'SSRF guard; remove this mark when one is added')
def test_the_web_crawler_refuses_the_metadata_address(monkeypatch):
    import urllib.request
    from sajha.tools.impl.webcrawler_tool_refactored import ExtractContentTool
    attempted = []

    def no_network(req, *a, **kw):
        attempted.append(getattr(req, 'full_url', req))
        raise OSError('network disabled in this test')
    monkeypatch.setattr(urllib.request, 'urlopen', no_network)
    try:
        ExtractContentTool().execute({'url': 'http://169.254.169.254/latest/meta-data/'})
    except Exception:
        pass
    assert not attempted, f'the crawler tried to fetch {attempted}'

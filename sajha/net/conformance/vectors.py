"""
The test vectors of protocol §21 (§21.1 a signed request and its response, §21.3 a key record),
used by the conformance suite's library cases (SIG-01, SIG-12, REC-01, REC-02). The time of the
examples is T0 (2026-10-07T12:00:00Z); every example key is Ed25519 from the seed
``SHA-256("sajha-net example: <label>")``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

T0 = 1791374400.0
RESPONSE_CREATED = 1791374401
RESPONSE_KEYID = 'TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I'
RESPONSE_SIGNATURE = 'VsjDNqwP39vYvKv6QK79JlSp+PSgnZOkvcPpeSRlMmC66VzbfNBVxjHu+zDVbF5i/ZlMT6fPwDLXBGLVKWOBBg=='

CA_B64 = ('MIIBJjCB2aADAgECAgEBMAUGAytlcDApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwHhcNMjYxMDAxMDAw'
          'MDAwWhcNMzYxMDAxMDAwMDAwWjApMREwDwYDVQQKDAhhY21lLW5ldDEUMBIGA1UEAwwLYWNtZS1uZXQgQ0EwKjAFBgMrZXADIQAU74St'
          '0nczabbH0d6rF/LCbrZd+WHVAdsGiGlenT/aTqMmMCQwEgYDVR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8BAf8EBAMCAQYwBQYDK2VwA0EA'
          'nDomu6qIswXIkXAgTBkvJISwwprAH5TvqXTB0DsUObmJfREpDIpmZAbddLzNY5aJEBpCUsVES9KW50koegP7Dg==')
LEAF = (':MIIBSTCB/KADAgECAgMaKzwwBQYDK2VwMCkxETAPBgNVBAoMCGFjbWUtbmV0MRQwEgYDVQQDDAthY21lLW5ldCBDQTAeFw0yNjEwMDEw'
        'MDAwMDBaFw0yNjEwMzEwMDAwMDBaMCUxETAPBgNVBAoMCGFjbWUtbmV0MRAwDgYDVQQDDAdyaXNrLWV1MCowBQYDK2VwAyEAIWvGipO7Yb'
        'WU0Mxtr+alRgL4QiXNgPhYTBG2IOEdxKSjSzBJMAwGA1UdEwEB/wQCMAAwDgYDVR0PAQH/BAQDAgeAMCkGA1UdEQQiMCCCHnNhamhhLXJp'
        'c2stZXUuZXhhbXBsZS5pbnRlcm5hbDAFBgMrZXADQQCdjQWn60f/a+Co25hWcYkVpEm5gaan+h8jRb85AvE2F4vda21cPZJrjjZW6KpIht'
        'e1uVKZReH6ir3hYl6Xm7sJ:')
BODY = (b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"var_calc","arguments":{"portfolio":'
        b'"EU-RATES","confidence":0.99,"horizon_days":10},"_meta":{"io.modelcontextprotocol/protocolVersion":'
        b'"2026-07-28","io.modelcontextprotocol/clientCapabilities":{"extensions":{"io.sajha/net":{"protocol_version"'
        b':1}}},"traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01","io.sajha/net":{"home":'
        b'"risk-eu","qualified_name":"acme-net__cust-na__var_calc"}}}}')
COMPONENTS = ('("@method" "@path" "@query" "content-type" "content-digest" "mcp-protocol-version" "mcp-method" '
              '"mcp-name" "sajha-net-version" "sajha-net-name" "sajha-net-from" "sajha-net-to" "sajha-net-hop" '
              '"sajha-net-visited" "sajha-net-api-key" "traceparent")')
SIG_INPUT = (f'sajhanet={COMPONENTS};created=1791374400;nonce="q1QXbXk3WlNQ8n0Zr6dL4w";'
             'keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"')
HEADERS = {
    'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
    'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/call', 'Mcp-Name': 'var_calc',
    'Sajha-Net-Version': '1', 'Sajha-Net-Name': 'acme-net', 'Sajha-Net-From': 'risk-eu', 'Sajha-Net-To': 'cust-na',
    'Sajha-Net-Hop': '1', 'Sajha-Net-Visited': '"acme-net/risk-eu"',
    'Sajha-Net-Api-Key': 'sja_U7ctcH-MN6JrIdIlX_PfCVXKc79Rmt58aTub2E7N97E',
    'traceparent': '00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01',
    'Content-Digest': 'sha-256=:FH+YtinzXcDSV+F2IPdYvsdEmlqry1zKK1duKAzRDeI=:',
    'Sajha-Net-Certificate': LEAF, 'Signature-Input': SIG_INPUT,
    'Signature': 'sajhanet=:xHiAAzcYJVUZBiNqU+OYRIwVVv5I7DfVOTEws0KRlNbLHX9nyOmPPwEiojXWFOSS9su5gbZkm51gcf/nqPYPDQ==:'}
RESP_BODY = (b'{"jsonrpc":"2.0","id":7,"result":{"resultType":"complete","content":[{"type":"text","text":"{\\"var\\": '
             b'1843200.0, \\"currency\\": \\"EUR\\"}"}],"structuredContent":{"var":1843200.0,"currency":"EUR"},'
             b'"isError":false,"_meta":{"io.sajha/net":{"instance":"cust-na","data_classes":{"results":'
             b'["confidential"]}}}}}')
KEY_RECORD = {
    'type': 'key', 'net': 'acme-net', 'key_id': '0b6f3c1e-8a4d-4f7e-9c21-5d3e7a9b2f10', 'key_prefix': 'sja_U7ctcH-M...',
    'name': 'alice laptop', 'key_hash': '1db0e8728c95abfa10d2a7b40dabc56c240e72cc4c63d517815b22ac46f09ff4',
    'home_instance': 'risk-eu', 'owner': {'user_id': '7d2a9e44-1c3b-4b8e-a6f0-2e9d8c7b5a31', 'user_name': 'alice',
                                          'display_name': 'Alice Martin', 'roles': ['analyst']},
    'enabled': True, 'expires_at': '2027-04-01T00:00:00Z', 'revoked_at': None, 'tool_access_mode': 'allowlist',
    'tool_access_list': ['var_calc', 'stress_test'], 'persistent': False, 'version': 42,
    'updated_at': '2026-10-07T11:58:03Z',
    'signature': {'alg': 'ed25519', 'keyid': '_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ',
                  'sig': '0AFAefhoSn4sMYcjD95AcBYRf_Ik_GTQF2U1oKGlNtgaweBjdz9Ugjygjh5BenumgXzrW8NaHybd1ZXs6_hOBg'}}

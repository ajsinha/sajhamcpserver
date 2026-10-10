"""
The test vectors of protocol §21 (§21.1 a signed request and its response, §21.3 a key record,
§21.4 a signed event stream), used by the conformance suite's library cases (SIG-01, SIG-12, SIG-14,
REC-01, REC-02). The time of the
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

# ── §21.4 a signed event stream ────────────────────────────────────

#: cust-na's certificate (serial 0x1a2b3d, the profile of risk-eu's); its thumbprint is RESPONSE_KEYID
STREAM_HOST_CERT = ('MIIBSTCB/KADAgECAgMaKz0wBQYDK2VwMCkxETAPBgNVBAoMCGFjbWUtbmV0MRQwEgYDVQQDDAthY21lLW5ldCBDQTAeFw0yNjEw'
                    'MDEwMDAwMDBaFw0yNjEwMzEwMDAwMDBaMCUxETAPBgNVBAoMCGFjbWUtbmV0MRAwDgYDVQQDDAdjdXN0LW5hMCowBQYDK2VwAyEA'
                    'srvmxQI8Z9MuVaOgbf5X83PgH1fia/x2Ib9LVn74FFejSzBJMAwGA1UdEwEB/wQCMAAwDgYDVR0PAQH/BAQDAgeAMCkGA1UdEQQi'
                    'MCCCHnNhamhhLWN1c3QtbmEuZXhhbXBsZS5pbnRlcm5hbDAFBgMrZXADQQBXDlotfCaLjY23NFNof+JXo7iv1kKm/8kh9hY+Dlwb'
                    'BsWKvJzrKsiymfv9/prLu54rH8u206+ye5wRFNSyjDQL')
STREAM_NONCE = 'Zm9yd2FyZGVkLXN0cmVhbQ'
STREAM_PROGRESS_TOKEN = '4bf92f3577b34da6a3ce929d0e0e4736:8'
STREAM_BODY = (b'{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"var_calc","arguments":{"portfolio":'
               b'"EU-RATES","confidence":0.99,"horizon_days":10},"_meta":{"io.modelcontextprotocol/protocolVersion":'
               b'"2026-07-28","io.modelcontextprotocol/clientCapabilities":{"extensions":{"io.sajha/net":'
               b'{"protocol_version":1}}},"io.modelcontextprotocol/logLevel":"info","progressToken":'
               b'"4bf92f3577b34da6a3ce929d0e0e4736:8","traceparent":"00-4bf92f3577b34da6a3ce929d0e0e4736-'
               b'00f067aa0ba902b7-01","io.sajha/net":{"home":"risk-eu","qualified_name":"acme-net__cust-na__var_calc",'
               b'"stream":1}}}}')
STREAM_HEADERS = dict(HEADERS, **{
    'Content-Digest': 'sha-256=:4HGry7yp3KlU/KycYmimsQlKN4sWMPGe/cX5QOlhPs4=:',
    'Signature-Input': (f'sajhanet={COMPONENTS};created=1791374400;nonce="{STREAM_NONCE}";'
                        'keyid="_9toR0iCB-Uqt342hN98Scc5b_lGbZ_OZyriwc0-KTQ";alg="ed25519";tag="sajha-net-v1"'),
    'Signature': 'sajhanet=:akpG0vjkrQbKzKbBevPJNj4uDrbe7uW0WqS48a/W3G6iISxf8+6UCkmZ4CTFi3WDfASbA1VF10D8mPOeZceGBw==:'})
STREAM_RESPONSE_HEADERS = {
    'Content-Type': 'text/event-stream', 'Sajha-Net-Version': '1', 'Sajha-Net-Name': 'acme-net',
    'Sajha-Net-From': 'cust-na', 'Sajha-Net-To': 'risk-eu', 'Sajha-Net-Certificate': f':{STREAM_HOST_CERT}:',
    'Signature-Input': ('sajhanet=("@status" "content-type" "sajha-net-version" "sajha-net-name" "sajha-net-from" '
                        '"sajha-net-to" "signature";req;key="sajhanet");created=1791374401;'
                        f'keyid="{RESPONSE_KEYID}";alg="ed25519";tag="sajha-net-v1"'),
    'Signature': 'sajhanet=:BMgdE3fZaMa1T/8/2i2rE61PmlLeKrqCto3QiUrw8idg+7nkz3jGCbpGi9sdqhszaeVUqw/ADjbxM2g1oC3bAQ==:'}
#: c0 .. c3 (lowercase hex): c0 binds the stream to the request's signature, c_i follows event i
STREAM_CHAIN = (
    '77bf8f635c1c7322055c70f8095ae147cd6a9d665e410265705dbd3c670b5ff5',
    '0b77cd1d351a16d41072e1efcc71728d5bafc1c2cf547b3b0e2bccbb4459c11d',
    '82e35ab4ae84cd1e107987a342f839f74d9510d980f5f2a8a3f13e5accf9f8da',
    '2d01d71acb71561e0c3310a5a7d8e913690a35c00c6f0f1934aa689339246265',
)
#: the three signed events, as sent (compact JSON, members in the order shown in §21.4)
STREAM_EVENTS = (
    (b'{"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"4bf92f3577b34da6a3ce92'
     b'9d0e0e4736:8","progress":1,"total":3,"message":"loading positions","_meta":{"io.sajha/net":{"event_s'
     b'ignature":{"alg":"ed25519","keyid":"TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I","seq":1,"sig":"zHUb'
     b'-hfKvLkAEHf9BnRFOmZqJW1XR1UIFeV4A4R8CfBvuxm_HPRVjV-i1ij1ai5M3CJ67XTuRkfN6SA38MwUCg"}}}}}'),
    (b'{"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info","logger":"var_calc","data'
     b'":"1240 positions loaded","_meta":{"io.sajha/net":{"event_signature":{"alg":"ed25519","keyid":"TYgEy'
     b'Z0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I","seq":2,"sig":"5MeM9_FPLpjL2rWAgPqCHsf-ram6nDmgIelRllo4Q_Obu'
     b'O_jBhLmWEMBY8_Jx6DAvAMg7dO-8QnyfX0tDoZiAw"}}}}}'),
    (b'{"jsonrpc":"2.0","method":"notifications/progress","params":{"progressToken":"4bf92f3577b34da6a3ce92'
     b'9d0e0e4736:8","progress":2,"total":3,"message":"simulating","_meta":{"io.sajha/net":{"event_signatur'
     b'e":{"alg":"ed25519","keyid":"TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I","seq":3,"sig":"oQL5TQgO--j'
     b'NmTjLOiNDCUXJF4hUoCpbAbjO9WIo2ySWXdxW2cPqPqNBrId_WR1oFAz5sZ1oeyTJ3cr6flAyCg"}}}}}'),
)
#: the signed final message
STREAM_FINAL = (b'{"jsonrpc":"2.0","id":8,"result":{"resultType":"complete","content":[{"type":"text","text":"{\\"var\\"'
                b': 1843200.0, \\"currency\\": \\"EUR\\"}"}],"structuredContent":{"var":1843200.0,"currency":"EUR"},"isErr'
                b'or":false,"_meta":{"io.sajha/net":{"instance":"cust-na","data_classes":{"results":["confidential"]},'
                b'"stream":{"seq":4,"chain":"2d01d71acb71561e0c3310a5a7d8e913690a35c00c6f0f1934aa689339246265"},"respo'
                b'nse_signature":{"alg":"ed25519","keyid":"TYgEyZ0EpjoyDRl0LSBetA_dB5YYBOYN-zdRoXl2n-I","sig":"D3sU4WP'
                b'Jn0LQjn9LbxjBpxVIfKL24ZWXoqMe3MjgKQnH0xBrMgZQfxAkkqr5-dXbUMBQRN9ONzfnCdds89NnBQ","request_nonce":"Zm'
                b'9yd2FyZGVkLXN0cmVhbQ"}}}}}')
#: c4, over the final message without response_signature: what both sides audit
STREAM_TRANSCRIPT = 'b98024b364e7e6dd7fc1bbedca7f3b6350b3e67a4d9be5a383a45fe7f864c0ca'

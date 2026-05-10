"""
Tests for sajha.auth — password, JWT, AuthManager.
"""

import os
import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))


class TestPassword:
    """bcrypt hashing and verification."""

    def test_hash_returns_string(self):
        from sajha.auth.password import hash_password
        h = hash_password('test123')
        assert isinstance(h, str)
        assert h.startswith('$2b$')

    def test_verify_correct(self):
        from sajha.auth.password import hash_password, verify_password
        h = hash_password('secret')
        assert verify_password('secret', h) is True

    def test_verify_wrong(self):
        from sajha.auth.password import hash_password, verify_password
        h = hash_password('secret')
        assert verify_password('wrong', h) is False

    def test_different_hashes(self):
        from sajha.auth.password import hash_password
        h1 = hash_password('same')
        h2 = hash_password('same')
        assert h1 != h2  # Different salts

    def test_empty_password(self):
        from sajha.auth.password import hash_password, verify_password
        h = hash_password('')
        assert verify_password('', h) is True
        assert verify_password('x', h) is False

    def test_unicode_password(self):
        from sajha.auth.password import hash_password, verify_password
        h = hash_password('пароль密码パスワード')
        assert verify_password('пароль密码パスワード', h) is True

    def test_long_password(self):
        from sajha.auth.password import hash_password, verify_password
        pwd = 'a' * 72  # bcrypt max
        h = hash_password(pwd)
        assert verify_password(pwd, h) is True

    def test_verify_invalid_hash(self):
        from sajha.auth.password import verify_password
        assert verify_password('test', 'not-a-hash') is False


class TestJWT:
    """JWT token creation and decoding."""

    def test_create_and_decode(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', ['admin', 'user'])
        payload = decode_access_token(token)
        assert payload is not None
        assert payload['sub'] == 'user1'
        assert payload['roles'] == ['admin', 'user']
        assert payload['iss'] == 'sajha-mcp-server'

    def test_expired_token(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', ['user'], expires_minutes=-1)
        payload = decode_access_token(token)
        assert payload is None  # Expired

    def test_invalid_token(self):
        from sajha.auth.jwt_handler import decode_access_token
        assert decode_access_token('garbage.token.here') is None

    def test_tampered_token(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', ['user'])
        tampered = token[:-5] + 'XXXXX'
        assert decode_access_token(tampered) is None

    def test_extra_claims(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', ['user'], extra_claims={'org': 'acme'})
        payload = decode_access_token(token)
        assert payload['org'] == 'acme'

    def test_custom_expiry(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', ['user'], expires_minutes=1440)
        payload = decode_access_token(token)
        assert payload is not None

    def test_empty_roles(self):
        from sajha.auth.jwt_handler import create_access_token, decode_access_token
        token = create_access_token('user1', [])
        payload = decode_access_token(token)
        assert payload['roles'] == []

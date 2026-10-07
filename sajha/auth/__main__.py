"""
SAJHA MCP Server — credential commands.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    python -m sajha.auth rehash      hash every plain password and API key in the database
                                     (do this after setting auth.credential_storage: hashed)

Passwords become bcrypt values; API keys keep their SHA-256 (``key_hash``) and lose the raw
``key_value``. The administrators' files (config/users.json, config/apikeys.json) are not
changed: edit them by hand or through their pages. docs/security/Security Model.md
"""

from __future__ import annotations

import sys


def rehash() -> int:
    from sajha.auth.password import bcrypt_hash, is_bcrypt
    from sajha.core.config import get_settings
    from sajha.db.engine import get_db_session, init_db
    from sajha.db.models import ApiKey, User
    init_db(get_settings())
    db = get_db_session()
    try:
        users = keys = 0
        for u in db.query(User).all():
            if u.password_hash and not is_bcrypt(u.password_hash):
                u.password_hash = bcrypt_hash(u.password_hash)
                users += 1
        for k in db.query(ApiKey).all():
            if k.key_value:
                k.key_value = None
                keys += 1
        db.commit()
    finally:
        db.close()
    print(f'rehashed {users} password(s); removed {keys} raw API key value(s)')
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['rehash']:
        return rehash()
    print(__doc__.strip().split('\n\n', 1)[1].split('\n\n')[0])
    return 2


if __name__ == '__main__':
    sys.exit(main())

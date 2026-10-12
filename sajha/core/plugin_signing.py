"""
SAJHA MCP Server — publisher signatures for plugins.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A signed plugin carries ``plugin.sig`` beside ``plugin.json``: a detached Ed25519 signature,
by its publisher, over the SHA-256 digest of every other file in the package::

    {
      "format": "sajha-plugin-signature/1",
      "plugin": "bloomberg-tools", "version": "1.2.0",
      "publisher": "trading-desk", "key_id": "3f9c0a1b2c3d4e5f",
      "algorithm": "ed25519",
      "files": {"plugin.json": "sha256:...", "tools/bloomberg_quote.json": "sha256:..."},
      "signature": "<base64 of the Ed25519 signature over the canonical JSON of every field above>"
    }

The canonical JSON is ``json.dumps(fields, sort_keys=True, separators=(',', ':'))`` in UTF-8 of
the fields other than ``signature``. ``key_id`` is the first 16 hex digits of the SHA-256 of the
raw 32-byte public key. ``__pycache__`` directories and ``*.pyc`` files are not part of a package
(loading a plugin writes them).

Verification (``verify``) gives one of

* ``trusted``    the signature verifies under a configured trusted key whose publisher name is
                 the one the signature claims, and the files are exactly the signed ones;
* ``unsigned``   no ``plugin.sig``;
* ``untrusted``  signed with a key that is not configured as trusted (it cannot be checked);
* ``invalid``    a malformed signature file, a file added, removed or changed, a name or version
                 that is not the manifest's, or a signature that does not verify under the trusted
                 key it names: tampering, always refused;
* ``unavailable`` signed, but the ``cryptography`` package is not installed here.

Trusted keys: ``plugins.trusted_keys`` (a list of ``<publisher>=<key>``) and the ``*.pub`` files in
``plugins.trusted_keys_dir`` (the publisher is the file name without ``.pub``); a key is a PEM
public key or the base64 of the raw 32 bytes. ``plugins.allow_unsigned`` (default ``true``, so
plugins that worked before keep loading, each with a warning notice) decides whether an unsigned
or untrusted plugin loads; ``false`` refuses it. Design: docs/security/Security Model.md, "Plugins".

Publisher command line::

    python -m sajha.core.plugin_signing keygen --publisher trading-desk --out keys/
    python -m sajha.core.plugin_signing sign config/plugins/bloomberg-tools --key keys/trading-desk.key \\
        --publisher trading-desk
    python -m sajha.core.plugin_signing verify config/plugins/bloomberg-tools --trusted keys/trading-desk.pub
    python -m sajha.core.plugin_signing pack config/plugins/bloomberg-tools --out dist/
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SIGNATURE_FILE = 'plugin.sig'
FORMAT = 'sajha-plugin-signature/1'
ALGORITHM = 'ed25519'
SIGNED_FIELDS = ('format', 'plugin', 'version', 'publisher', 'key_id', 'algorithm', 'files')
PUBLISHER_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')
DEFAULT_KEYS_DIR = 'config/plugin_keys'


class SigningError(ValueError):
    """A key or package that cannot be used for signing or verification."""


def crypto_available() -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: F401
        return True
    except Exception:
        return False


# ── package digests ──────────────────────────────────────────────────

def _skipped(rel: str) -> bool:
    parts = rel.split('/')
    return '__pycache__' in parts or rel.endswith('.pyc') or rel == SIGNATURE_FILE


def package_files(root) -> List[str]:
    """Every file of the package, relative, '/'-separated, sorted (``plugin.sig`` and bytecode left out).
    A symbolic link is refused: what is signed must be what loads."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != '__pycache__')
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():
                raise SigningError(f'{Path(dirpath, d).relative_to(root)} is a symbolic link')
        for name in filenames:
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if _skipped(rel):
                continue
            if p.is_symlink():
                raise SigningError(f'{rel} is a symbolic link')
            out.append(rel)
    return sorted(out)


def file_digests(root) -> Dict[str, str]:
    root = Path(root)
    return {rel: 'sha256:' + hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in package_files(root)}


def canonical(fields: Dict) -> bytes:
    return json.dumps({k: fields[k] for k in SIGNED_FIELDS}, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def package_hash(signature: Dict) -> str:
    """One digest for a signed package: what a reviewer approves (the signed fields and the signature)."""
    body = canonical(signature) + b'\n' + str(signature.get('signature', '')).encode('ascii', 'replace')
    return hashlib.sha256(body).hexdigest()


# ── keys ─────────────────────────────────────────────────────────────

def _raw_public(key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(public_key) -> str:
    raw = public_key if isinstance(public_key, (bytes, bytearray)) else _raw_public(public_key)
    return hashlib.sha256(bytes(raw)).hexdigest()[:16]


def load_public_key(text: str):
    """A PEM public key, or the base64 (standard or url-safe) of the raw 32 bytes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    text = (text or '').strip()
    if text.startswith('-----BEGIN'):
        key = serialization.load_pem_public_key(text.encode('ascii'))
        if not isinstance(key, ed25519.Ed25519PublicKey):
            raise SigningError('not an Ed25519 public key')
        return key
    try:
        raw = base64.b64decode(text + '=' * (-len(text) % 4), altchars=b'-_' if ('-' in text or '_' in text) else None,
                               validate=False)
    except Exception:
        raise SigningError('a public key must be PEM or the base64 of 32 raw bytes')
    if len(raw) != 32:
        raise SigningError('a raw Ed25519 public key is 32 bytes')
    return ed25519.Ed25519PublicKey.from_public_bytes(raw)


def load_private_key(text: str):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    key = serialization.load_pem_private_key(text.encode('ascii'), password=None)
    if not isinstance(key, ed25519.Ed25519PrivateKey):
        raise SigningError('not an Ed25519 private key')
    return key


def generate_keypair() -> Tuple[str, str]:
    """A new key pair as (private PEM, public PEM)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    priv = ed25519.Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode('ascii')
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii')
    return priv_pem, pub_pem


@dataclass
class TrustedKey:
    publisher: str
    key_id: str
    key: object = field(repr=False, default=None)
    origin: str = ''


def _setting_list(key: str) -> List[str]:
    try:
        from sajha.core.config import _list
        return [str(x).strip() for x in _list(key, []) if str(x).strip()]
    except Exception:
        return []


def _setting(key: str, default: str) -> str:
    try:
        from sajha.core.config import _get
        v = _get(key, default)
        return default if v is None else str(v)
    except Exception:
        return default


def allow_unsigned() -> bool:
    """``plugins.allow_unsigned`` (default true: plugins that loaded before keep loading, with a notice)."""
    try:
        from sajha.core.config import _bool
        return _bool('plugins.allow_unsigned', True)
    except Exception:
        return True


def trusted_keys(entries: Optional[List[str]] = None, keys_dir: Optional[str] = None,
                 origin: str = 'plugins.trusted_keys') -> Dict[str, TrustedKey]:
    """The configured trusted publisher keys, by key id. A bad entry is logged and skipped. ``origin``:
    where ``entries`` came from, as reported with a trusted verdict (the setting, or a --trusted file)."""
    out: Dict[str, TrustedKey] = {}
    if not crypto_available():
        return out
    entries = _setting_list('plugins.trusted_keys') if entries is None else entries
    keys_dir = _setting('plugins.trusted_keys_dir', DEFAULT_KEYS_DIR) if keys_dir is None else keys_dir
    pairs: List[Tuple[str, str, str]] = []
    for e in entries:
        name, sep, text = e.partition('=')
        if not sep:
            logger.warning(f'{origin}: an entry is not <publisher>=<key>; skipped')
            continue
        pairs.append((name.strip(), text.strip(), origin))
    if keys_dir and os.path.isdir(keys_dir):
        for fname in sorted(os.listdir(keys_dir)):
            if fname.endswith('.pub'):
                try:
                    pairs.append((fname[:-4], Path(keys_dir, fname).read_text(encoding='ascii'),
                                  f'{keys_dir}/{fname}'))
                except Exception as e:
                    logger.warning(f'plugins: cannot read trusted key {fname}: {e}')
    for publisher, text, origin in pairs:
        if not PUBLISHER_RE.match(publisher):
            logger.warning(f'plugins: trusted key from {origin}: publisher name {publisher!r} is not valid; skipped')
            continue
        try:
            key = load_public_key(text)
        except Exception as e:
            logger.warning(f'plugins: trusted key for {publisher} ({origin}) is not usable: {e}')
            continue
        kid = key_id(key)
        out[kid] = TrustedKey(publisher=publisher, key_id=kid, key=key, origin=origin)
    return out


# ── sign and verify ──────────────────────────────────────────────────

def _manifest(root: Path) -> Dict:
    try:
        data = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise SigningError('no plugin.json')
    except ValueError as e:
        raise SigningError(f'plugin.json is not JSON: {e}')
    if not isinstance(data, dict) or not data.get('name'):
        raise SigningError('plugin.json has no name')
    return data


def sign(root, private_key_pem: str, publisher: str, write: bool = True) -> Dict:
    """Sign the package at ``root``; writes ``plugin.sig`` (unless ``write`` is false) and returns it."""
    if not PUBLISHER_RE.match(publisher or ''):
        raise SigningError('publisher: 1-64 letters, digits, ".", "_" or "-", starting with a letter or digit')
    root = Path(root)
    m = _manifest(root)
    priv = load_private_key(private_key_pem)
    fields = {'format': FORMAT, 'plugin': str(m['name']), 'version': str(m.get('version', '0.0.0')),
              'publisher': publisher, 'key_id': key_id(priv.public_key()), 'algorithm': ALGORITHM,
              'files': file_digests(root)}
    sig = dict(fields, signature=base64.b64encode(priv.sign(canonical(fields))).decode('ascii'))
    if write:
        (root / SIGNATURE_FILE).write_text(json.dumps(sig, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return sig


@dataclass
class Verdict:
    status: str                       # trusted | unsigned | untrusted | invalid | unavailable
    detail: str = ''
    publisher: str = ''
    key_id: str = ''
    plugin: str = ''
    version: str = ''
    package_hash: str = ''
    files: Dict[str, str] = field(default_factory=dict)

    @property
    def trusted(self) -> bool:
        return self.status == 'trusted'

    def to_dict(self) -> Dict:
        return {'status': self.status, 'detail': self.detail, 'publisher': self.publisher, 'key_id': self.key_id,
                'plugin': self.plugin, 'version': self.version, 'package_hash': self.package_hash}


def read_signature(root) -> Optional[Dict]:
    p = Path(root) / SIGNATURE_FILE
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise SigningError(f'{SIGNATURE_FILE} is not a JSON object')
    return data


def verify(root, keys: Optional[Dict[str, TrustedKey]] = None) -> Verdict:
    """What the package at ``root`` is: see the module docstring. Never raises."""
    root = Path(root)
    try:
        sig = read_signature(root)
    except Exception as e:
        return Verdict('invalid', f'{SIGNATURE_FILE} cannot be read: {e}')
    if sig is None:
        return Verdict('unsigned', 'the plugin has no publisher signature (plugin.sig)')
    missing = [k for k in SIGNED_FIELDS + ('signature',) if k not in sig]
    if missing:
        return Verdict('invalid', f'{SIGNATURE_FILE} lacks {", ".join(missing)}')
    v = Verdict('invalid', publisher=str(sig.get('publisher')), key_id=str(sig.get('key_id')),
                plugin=str(sig.get('plugin')), version=str(sig.get('version')),
                files=dict(sig.get('files') or {}) if isinstance(sig.get('files'), dict) else {})
    if sig.get('format') != FORMAT or sig.get('algorithm') != ALGORITHM:
        v.detail = f'unsupported signature format {sig.get("format")!r} / algorithm {sig.get("algorithm")!r}'
        return v
    try:
        v.package_hash = package_hash(sig)
        m = _manifest(root)
        if str(m['name']) != v.plugin or str(m.get('version', '0.0.0')) != v.version:
            v.detail = (f'the signature is for {v.plugin} {v.version}, the manifest says '
                        f'{m["name"]} {m.get("version", "0.0.0")}')
            return v
        actual = file_digests(root)
    except Exception as e:
        v.detail = str(e)
        return v
    added = sorted(set(actual) - set(v.files))
    removed = sorted(set(v.files) - set(actual))
    changed = sorted(k for k in set(actual) & set(v.files) if actual[k] != v.files[k])
    if added or removed or changed:
        parts = []
        for label, names in (('added', added), ('removed', removed), ('changed', changed)):
            if names:
                parts.append(f'{label}: {", ".join(names[:5])}' + (' …' if len(names) > 5 else ''))
        v.detail = 'the files are not the signed ones (' + '; '.join(parts) + ')'
        return v
    if not crypto_available():
        v.status, v.detail = 'unavailable', 'signed, but the cryptography package is not installed to verify it'
        return v
    keys = trusted_keys() if keys is None else keys
    tk = keys.get(v.key_id)
    if tk is None:
        v.status = 'untrusted'
        v.detail = f'signed by {v.publisher} with key {v.key_id}, which is not a configured trusted key'
        return v
    if tk.publisher != v.publisher:
        v.detail = f'key {v.key_id} is trusted for publisher {tk.publisher}, but the signature claims {v.publisher}'
        return v
    try:
        tk.key.verify(base64.b64decode(str(sig['signature'])), canonical(sig))
    except Exception:
        v.detail = f'the signature does not verify under {tk.publisher}\'s key {v.key_id}'
        return v
    v.status, v.detail = 'trusted', f'signed by {v.publisher} (key {v.key_id}, {tk.origin})'
    return v


def gate(root, name: str) -> Tuple[List[str], Verdict]:
    """The load-time check ``PluginManager.validate`` runs: (errors, verdict). Raises the
    ``plugins.unsigned:<name>`` notice for an unsigned or untrusted plugin that loads anyway, the
    ``plugins.signature:<name>`` notice for one refused; clears both for a trusted one."""
    v = verify(root)
    errors: List[str] = []
    if v.status == 'invalid':
        errors.append(f'publisher signature invalid: {v.detail}')
    elif v.status != 'trusted' and not allow_unsigned():
        errors.append(f'{v.detail}; refused because plugins.allow_unsigned is false')
    try:
        from sajha import notices
        if errors:
            notices.clear_notice(f'plugins.unsigned:{name}')
            notices.raise_notice(f'plugins.signature:{name}', severity='error', source='plugins',
                                 title=f'Plugin {name} refused', detail=errors[0], ttl_minutes=0)
        elif v.status != 'trusted':
            notices.clear_notice(f'plugins.signature:{name}')
            notices.raise_notice(f'plugins.unsigned:{name}', severity='warning', source='plugins',
                                 title=f'Plugin {name} loaded without a trusted signature',
                                 detail=f'{v.detail}. It loads because plugins.allow_unsigned is true; sign it '
                                        f'and configure the publisher key, or set plugins.allow_unsigned: false '
                                        f'to refuse such plugins.', ttl_minutes=0)
        else:
            notices.clear_notice(f'plugins.unsigned:{name}')
            notices.clear_notice(f'plugins.signature:{name}')
    except Exception as e:
        logger.debug(f'plugins: notice for {name}: {e}')
    return errors, v


# ── packing (a zip for a catalog) ────────────────────────────────────

def pack(root, out_dir) -> str:
    """Zip a (signed) package as ``<name>-<version>.zip`` with its files at the top level."""
    import zipfile
    root = Path(root)
    m = _manifest(root)
    os.makedirs(out_dir, exist_ok=True)
    target = Path(out_dir) / f'{m["name"]}-{m.get("version", "0.0.0")}.zip'
    names = package_files(root) + ([SIGNATURE_FILE] if (root / SIGNATURE_FILE).is_file() else [])
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in names:
            z.write(root / rel, rel)
    return str(target)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog='python -m sajha.core.plugin_signing',
                                 description='Sign and verify SAJHA plugins (Ed25519 publisher signatures).')
    sub = ap.add_subparsers(dest='cmd', required=True)
    k = sub.add_parser('keygen', help='create a publisher key pair (<publisher>.key and <publisher>.pub)')
    k.add_argument('--publisher', required=True)
    k.add_argument('--out', default='.')
    s = sub.add_parser('sign', help='write plugin.sig into a plugin directory')
    s.add_argument('plugin_dir')
    s.add_argument('--key', required=True, help='the publisher private key (PEM)')
    s.add_argument('--publisher', required=True)
    v = sub.add_parser('verify', help='verify a plugin directory')
    v.add_argument('plugin_dir')
    v.add_argument('--trusted', action='append', default=[], help='a trusted <publisher>.pub (repeatable); '
                   'default: the configured trusted keys')
    p = sub.add_parser('pack', help='zip a plugin directory for a catalog')
    p.add_argument('plugin_dir')
    p.add_argument('--out', default='.')
    a = ap.parse_args(argv)
    if a.cmd in ('keygen', 'sign', 'verify') and not crypto_available():
        print('the cryptography package is required')
        return 2
    try:
        if a.cmd == 'keygen':
            if not PUBLISHER_RE.match(a.publisher):
                raise SigningError('publisher: 1-64 letters, digits, ".", "_" or "-"')
            priv, pub = generate_keypair()
            os.makedirs(a.out, exist_ok=True)
            kp = Path(a.out) / f'{a.publisher}.key'
            fd = os.open(kp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(priv)
            (Path(a.out) / f'{a.publisher}.pub').write_text(pub, encoding='ascii')
            print(f'wrote {kp} (keep it secret) and {a.publisher}.pub (key id {key_id(load_public_key(pub))})')
        elif a.cmd == 'sign':
            sig = sign(a.plugin_dir, Path(a.key).read_text(encoding='ascii'), a.publisher)
            print(f'signed {sig["plugin"]} {sig["version"]}: {len(sig["files"])} file(s), key {sig["key_id"]}')
        elif a.cmd == 'verify':
            keys = None
            if a.trusted:
                keys = {}
                for t in a.trusted:              # each key reports the file it came from, not the setting
                    keys.update(trusted_keys([f'{Path(t).name[:-4] if t.endswith(".pub") else Path(t).name}='
                                              f'{Path(t).read_text(encoding="ascii")}'], keys_dir='',
                                             origin=f'--trusted {t}'))
            r = verify(a.plugin_dir, keys)
            print(f'{r.status}: {r.detail}')
            return 0 if r.trusted else 1
        elif a.cmd == 'pack':
            print(pack(a.plugin_dir, a.out))
    except (SigningError, OSError, ValueError) as e:
        print(f'error: {e}')
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

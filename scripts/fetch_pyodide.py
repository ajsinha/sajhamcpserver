#!/usr/bin/env python3
"""
Vendor a pinned Pyodide release for the Python Playground (/playground).

SAJHA's Content-Security-Policy is self-only, so by default (``playground.assets: vendored``)
the playground loads Pyodide from ``sajha/web/static/vendor/pyodide/<version>/``. This script
puts it there:

  1. downloads ``pyodide-core-<version>.tar.bz2`` from the GitHub release and checks its
     SHA-256 against the digest GitHub publishes for that asset (or the one pinned below);
  2. unpacks the browser files (pyodide.mjs, pyodide.asm.mjs, pyodide.asm.wasm,
     python_stdlib.zip, pyodide-lock.json, ...) — the Node CLI files are skipped;
  3. reads ``pyodide-lock.json`` from that verified archive and downloads the wheels for the
     requested packages and everything they depend on, checking each wheel's SHA-256
     against the lockfile;
  4. writes ``sajha-manifest.json`` (version, packages, sizes), which the server reads to
     tell whether the assets are present.

Usage:
    python scripts/fetch_pyodide.py                     # the version in playground.pyodide_version
    python scripts/fetch_pyodide.py --version 314.0.7 --packages numpy pandas
    python scripts/fetch_pyodide.py --list              # show the dependency closure and stop

The downloaded files are git-ignored (see the README.md and .gitignore in the destination).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / 'sajha' / 'web' / 'static' / 'vendor' / 'pyodide'

#: The packages the playground preloads on demand (plus everything they depend on).
DEFAULT_PACKAGES = ['numpy', 'pandas', 'matplotlib', 'scipy', 'scikit-learn', 'statsmodels',
                    'sympy', 'micropip']

#: Core-archive digests checked into the repository, so the pinned release verifies even
#: without the GitHub API. Other versions use the digest GitHub publishes for the asset.
PINNED_CORE_SHA256 = {
    '314.0.7': '2abdcc2e35208af406e07724cffa85bc582ced97e9028383ecf5462541393f95',
}

#: Files from the core archive the browser needs (the rest are the Node CLI and type stubs).
CORE_FILES = {'pyodide.js', 'pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.js', 'pyodide.asm.wasm',
              'python_stdlib.zip', 'pyodide-lock.json', 'package.json'}

GITHUB_DL = 'https://github.com/pyodide/pyodide/releases/download/{v}/pyodide-core-{v}.tar.bz2'
GITHUB_API = 'https://api.github.com/repos/pyodide/pyodide/releases/tags/{v}'
CDN = 'https://cdn.jsdelivr.net/pyodide/v{v}/full/'

VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
UA = {'User-Agent': 'sajha-fetch-pyodide/1'}


def _configured_version() -> str:
    """playground.pyodide_version, read the way the server reads it (env, YAML, default)."""
    sys.path.insert(0, str(ROOT))
    try:
        from sajha.web.playground import DEFAULT_PYODIDE_VERSION
        from sajha.core.config import _get
        return _get('playground.pyodide_version', DEFAULT_PYODIDE_VERSION) or DEFAULT_PYODIDE_VERSION
    except Exception:
        return '314.0.7'


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:          # transient network errors: retry twice
            last = e
            time.sleep(1 + attempt * 2)
    raise RuntimeError(f'download failed: {url}: {last}')


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected_core_digest(version: str) -> str:
    if version in PINNED_CORE_SHA256:
        return PINNED_CORE_SHA256[version]
    rel = json.loads(_get(GITHUB_API.format(v=version)))
    name = f'pyodide-core-{version}.tar.bz2'
    for a in rel.get('assets', []):
        if a.get('name') == name and str(a.get('digest', '')).startswith('sha256:'):
            return a['digest'].split(':', 1)[1]
    raise RuntimeError(f'GitHub publishes no sha256 digest for {name}; refusing to install unverified files')


def closure(lock: dict, names) -> list:
    """The requested packages and their transitive dependencies, by lockfile name."""
    pkgs = lock['packages']
    seen, out = set(), []

    def walk(n):
        key = n.lower()
        if key in seen:
            return
        if key not in pkgs:
            raise SystemExit(f'package {n!r} is not in this Pyodide release')
        seen.add(key)
        for d in pkgs[key].get('depends', []):
            walk(d)
        out.append(key)

    for n in names:
        walk(n)
    return sorted(out)


def fetch(version: str, packages, dest: Path, force: bool = False, list_only: bool = False) -> dict:
    if not VERSION_RE.match(version):
        raise SystemExit(f'not a Pyodide version: {version!r}')
    target = dest / version
    manifest_path = target / 'sajha-manifest.json'

    print(f'Pyodide {version}: verifying the core archive')
    expected = _expected_core_digest(version)
    blob = _get(GITHUB_DL.format(v=version), timeout=300)
    got = _sha256(blob)
    if got != expected:
        raise SystemExit(f'checksum mismatch for the core archive: expected {expected}, got {got}')
    print(f'  core archive OK ({len(blob) / 1e6:.1f} MB, sha256 {got[:16]}…)')

    members = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:bz2') as tf:
        for m in tf.getmembers():
            base = m.name.split('/', 1)[-1]
            if m.isfile() and '/' not in base and base in CORE_FILES:
                members[base] = tf.extractfile(m).read()
    lock = json.loads(members['pyodide-lock.json'])
    wanted = closure(lock, packages)
    if list_only:
        for n in wanted:
            print(f"  {n:22} {lock['packages'][n]['file_name']}")
        return {}

    if target.exists() and force:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.fetch-', dir=target))
    try:
        for name, data in members.items():
            (tmp / name).write_bytes(data)
        sizes = {}
        for n in wanted:
            info = lock['packages'][n]
            fn = info['file_name']
            existing = target / fn
            if existing.exists() and _sha256(existing.read_bytes()) == info['sha256']:
                shutil.copy2(existing, tmp / fn)
                sizes[n] = existing.stat().st_size
                print(f'  {n:22} cached')
                continue
            data = _get(CDN.format(v=version) + fn, timeout=300)
            if _sha256(data) != info['sha256']:
                raise SystemExit(f'checksum mismatch for {fn} (lockfile sha256 {info["sha256"]})')
            (tmp / fn).write_bytes(data)
            sizes[n] = len(data)
            print(f'  {n:22} {len(data) / 1e6:6.1f} MB  sha256 OK')
        manifest = {
            'version': version,
            'requested': list(packages),
            'packages': wanted,
            'core_sha256': got,
            'bytes': sum(f.stat().st_size for f in tmp.iterdir() if f.is_file()),
            'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        (tmp / 'sajha-manifest.json').write_text(json.dumps(manifest, indent=2))
        # Replace the old files only once everything has verified.
        for f in tmp.iterdir():
            os.replace(f, target / f.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f'Installed {len(wanted)} packages, {manifest["bytes"] / 1e6:.1f} MB, in {target}')
    print(f'Manifest: {manifest_path}')
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--version', default=None, help='Pyodide version (default: playground.pyodide_version)')
    ap.add_argument('--packages', nargs='*', default=DEFAULT_PACKAGES,
                    help='packages to vendor, with their dependencies (default: %(default)s)')
    ap.add_argument('--dest', default=str(DEST), help='destination folder (default: %(default)s)')
    ap.add_argument('--force', action='store_true', help='delete the version folder first')
    ap.add_argument('--list', action='store_true', help='print the dependency closure and stop')
    a = ap.parse_args(argv)
    fetch(a.version or _configured_version(), a.packages, Path(a.dest), force=a.force, list_only=a.list)
    return 0


if __name__ == '__main__':
    sys.exit(main())

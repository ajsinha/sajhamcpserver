"""SAJHA pod seed step (init container; same image as the server).

1. Copies the image's config/ and sajha/tools/impl/ into the writable volumes mounted
   at /seed/config and /seed/impl.  SEED_MODE=missing (default) copies only files the
   volume does not have, so admin and MCP Studio edits on a persistent volume survive;
   SEED_MODE=overwrite replaces them with the image's copies.
2. Writes /seed/config/application.yml: the image's application.yml with
   /etc/sajha/overrides.yaml deep-merged in (maps merge; lists and scalars replace).
   Rewritten at every start, so the chart's values are the authority for this file.
3. Waits (WAIT_FOR="host:port host:port", up to WAIT_TIMEOUT seconds) until the bundled
   Redis and the PostgreSQL server accept TCP connections: the server refuses to start
   when a shared state store does not answer, and would otherwise restart once.
"""
import os
import shutil
import socket
import sys
import time
from pathlib import Path

import yaml

MODE = os.environ.get('SEED_MODE', 'missing')
IMAGE_CONFIG = Path('/app/config')
IMAGE_IMPL = Path('/app/sajha/tools/impl')
OVERRIDES = Path('/etc/sajha/overrides.yaml')


def copy_tree(src: Path, dst: Path) -> int:
    n = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        target = dst / Path(root).relative_to(src)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            out = target / name
            if out.exists() and MODE != 'overwrite':
                continue
            shutil.copyfile(Path(root) / name, out)
            n += 1
    return n


def merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def wait_for(targets: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    for target in targets.split():
        host, _, port = target.rpartition(':')
        while True:
            try:
                socket.create_connection((host, int(port)), timeout=3).close()
                print(f'seed: {target} is accepting connections')
                break
            except OSError as e:
                if time.monotonic() > deadline:
                    print(f'seed: {target} still unreachable ({e}); starting anyway', file=sys.stderr)
                    return False
                time.sleep(2)
    return True


def main() -> int:
    copied = copy_tree(IMAGE_CONFIG, Path('/seed/config'))
    copied += copy_tree(IMAGE_IMPL, Path('/seed/impl'))
    base = yaml.safe_load((IMAGE_CONFIG / 'application.yml').read_text(encoding='utf-8')) or {}
    extra = {}
    if OVERRIDES.exists():
        extra = yaml.safe_load(OVERRIDES.read_text(encoding='utf-8')) or {}
    if not isinstance(extra, dict):
        print('seed: overrides.yaml must be a mapping', file=sys.stderr)
        return 1
    out = Path('/seed/config/application.yml')
    tmp = out.with_name('.application.yml.tmp')
    tmp.write_text('# Generated at pod start from the image default and the chart\'s config.overrides.\n'
                   '# Edit the Helm values (or the overrides ConfigMap), not this file.\n'
                   + yaml.safe_dump(merge(base, extra), sort_keys=False, allow_unicode=True),
                   encoding='utf-8')
    os.replace(tmp, out)
    print(f'seed: {copied} file(s) copied (mode {MODE}); application.yml merged with '
          f'{len(extra)} top-level override key(s)')
    wait_for(os.environ.get('WAIT_FOR', ''), float(os.environ.get('WAIT_TIMEOUT', '180')))
    return 0


if __name__ == '__main__':
    sys.exit(main())

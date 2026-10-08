# Vendored Pyodide (Python Playground)

This folder holds the Pyodide release the Python Playground (`/playground`) loads when
`playground.assets` is `vendored` (the default). Everything here except this README and
`.gitignore` is downloaded, verified and git-ignored:

```
python scripts/fetch_pyodide.py            # the version in playground.pyodide_version
```

The script checks the core archive's SHA-256 against the digest the Pyodide GitHub release
publishes, then checks every package wheel against the SHA-256 in that release's
`pyodide-lock.json`. Files land in `<version>/`, with a `sajha-manifest.json` the server
reads to tell whether the assets are present.

Without these files the playground shows an administrator hint instead of loading. The
alternative is `playground.assets: cdn`, which loads Pyodide from
`https://cdn.jsdelivr.net/pyodide/v<version>/full/` and adds that origin to the playground's
Content-Security-Policy only.

The guide is `docs/getting-started/Python Playground.md`.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

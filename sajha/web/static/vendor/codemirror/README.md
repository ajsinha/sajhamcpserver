# CodeMirror 6 (Python Playground editor)

`codemirror-python.min.js` is a single IIFE bundle of CodeMirror 6 (MIT licence, Marijn
Haverbeke and others) with the Python language, built from `entry.js` here. It exposes
`window.SajhaEditor.create(parent, doc, {onRun, onChange, label})`. Colours come from
SAJHA's CSS tokens (`--pg-*`, `--t-*`), so the four themes need no JavaScript.

Rebuild (Node 18+):

```
npm install codemirror @codemirror/lang-python @codemirror/state @codemirror/view \
            @codemirror/commands @codemirror/language esbuild
npx esbuild entry.js --bundle --minify --format=iife --legal-comments=eof \
            --outfile=codemirror-python.min.js
```

Built from codemirror 6.0.2, @codemirror/view 6.43.13, @codemirror/lang-python 6.2.1.

---

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

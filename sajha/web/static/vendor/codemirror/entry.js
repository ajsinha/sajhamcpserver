/* Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com */
// SAJHA's CodeMirror 6 bundle: just Python editing. Built with esbuild, exposed as window.SajhaEditor.
import {EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection} from '@codemirror/view';
import {EditorState, Prec} from '@codemirror/state';
import {defaultKeymap, history, historyKeymap, indentWithTab} from '@codemirror/commands';
import {indentOnInput, bracketMatching, syntaxHighlighting, HighlightStyle, indentUnit} from '@codemirror/language';
import {python} from '@codemirror/lang-python';
import {tags as t} from '@lezer/highlight';

// Colours come from SAJHA's CSS tokens, so all four themes work without JS.
const style = HighlightStyle.define([
  {tag: [t.keyword, t.controlKeyword, t.definitionKeyword, t.operatorKeyword, t.moduleKeyword], color: 'var(--pg-kw)', fontWeight: '600'},
  {tag: [t.string, t.special(t.string)], color: 'var(--pg-str)'},
  {tag: [t.number, t.bool, t.null], color: 'var(--pg-num)'},
  {tag: [t.comment, t.lineComment], color: 'var(--pg-comment)', fontStyle: 'italic'},
  {tag: [t.function(t.variableName), t.function(t.propertyName), t.definition(t.function(t.variableName))], color: 'var(--pg-fn)'},
  {tag: [t.className, t.definition(t.className)], color: 'var(--pg-fn)', fontWeight: '600'},
  {tag: [t.self, t.special(t.variableName)], color: 'var(--pg-kw)'},
]);

const theme = EditorView.theme({
  '&': {fontSize: '13px', backgroundColor: 'var(--t-inp)', color: 'var(--t-inp-t)'},
  '.cm-content': {fontFamily: '"JetBrains Mono", ui-monospace, monospace', caretColor: 'var(--t-inp-t)'},
  '.cm-gutters': {backgroundColor: 'transparent', color: 'var(--t-muted)', border: 'none'},
  '.cm-activeLine': {backgroundColor: 'color-mix(in srgb, var(--t-inp-fb) 7%, transparent)'},
  '.cm-activeLineGutter': {backgroundColor: 'transparent', color: 'var(--t-text)'},
  '&.cm-focused': {outline: 'none'},
  '.cm-cursor': {borderLeftColor: 'var(--t-inp-t)'},
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, ::selection': {backgroundColor: 'color-mix(in srgb, var(--t-inp-fb) 25%, transparent) !important'},
  '.cm-matchingBracket': {backgroundColor: 'color-mix(in srgb, var(--t-inp-fb) 20%, transparent)', outline: 'none'},
});

function create(parent, doc, opts) {
  opts = opts || {};
  const run = (shift) => () => { if (opts.onRun) opts.onRun(shift); return true; };
  const view = new EditorView({
    parent,
    state: EditorState.create({
      doc: doc || '',
      extensions: [
        lineNumbers(), highlightActiveLineGutter(), highlightActiveLine(), drawSelection(), history(),
        indentOnInput(), bracketMatching(), indentUnit.of('    '), python(), syntaxHighlighting(style), theme,
        Prec.highest(keymap.of([
          {key: 'Mod-Enter', run: run(false)},
          {key: 'Shift-Enter', run: run(true)},
        ])),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        EditorView.updateListener.of((u) => { if (u.docChanged && opts.onChange) opts.onChange(); }),
        EditorView.contentAttributes.of({'aria-label': opts.label || 'Python code'}),
      ],
    }),
  });
  return {
    view,
    getValue: () => view.state.doc.toString(),
    setValue: (s) => view.dispatch({changes: {from: 0, to: view.state.doc.length, insert: s || ''}}),
    focus: () => view.focus(),
    destroy: () => view.destroy(),
  };
}

window.SajhaEditor = {create};

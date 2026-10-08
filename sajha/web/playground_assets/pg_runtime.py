# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The Python Playground's cell runner. Runs inside Pyodide in the browser's Web Worker
(see worker.mjs); the server never executes it.

run_cell(code) evaluates a cell in one shared namespace, like a notebook kernel: the value
of a final expression is shown as a REPL would (HTML for objects with _repr_html_, such as
pandas DataFrames), and matplotlib figures are rendered to PNG when plt.show() is called
or the cell ends. display(obj) shows a value mid-cell.
"""

import base64
import io
import os
import sys

import _pg_js  # registered by worker.mjs: emit(kind, text)
from pyodide.code import eval_code_async

# matplotlib draws with Agg; plt.show() hands the figures to the page (module pg_backend).
_BACKEND = '''from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.backend_bases import FigureManagerBase as FigureManager


def show(*args, **kwargs):
    import pg_runtime
    pg_runtime._flush_figures()
'''
with open('/home/pyodide/pg_backend.py', 'w') as _f:
    _f.write(_BACKEND)
if '/home/pyodide' not in sys.path:
    sys.path.insert(0, '/home/pyodide')
os.environ['MPLBACKEND'] = 'module://pg_backend'

MAX_REPR = 20000
MAX_HTML = 400000

namespace = {'__name__': '__main__'}


def _emit(kind, text):
    _pg_js.emit(kind, text)


def _clip(s, limit):
    return s if len(s) <= limit else s[:limit] + f'\n… ({len(s) - limit} more characters)'


def _flush_figures():
    plt = sys.modules.get('matplotlib.pyplot')
    if plt is None:
        return
    for num in list(plt.get_fignums()):
        fig = plt.figure(num)
        buf = io.BytesIO()
        try:
            fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
            _emit('image/png', base64.b64encode(buf.getvalue()).decode('ascii'))
        finally:
            plt.close(fig)


def display(*objs):
    """Show values now (HTML for DataFrames, PNG for matplotlib figures, repr otherwise)."""
    for obj in objs:
        _show(obj)


def _show(value):
    if value is None:
        return
    mod = type(value).__module__ or ''
    if mod.startswith('matplotlib') and hasattr(value, 'savefig'):
        buf = io.BytesIO()
        value.savefig(buf, format='png', dpi=110, bbox_inches='tight')
        _emit('image/png', base64.b64encode(buf.getvalue()).decode('ascii'))
        return
    html = getattr(value, '_repr_html_', None)
    if callable(html):
        try:
            h = html()
            if h:
                _emit('text/html', _clip(str(h), MAX_HTML))
                return
        except Exception:
            pass
    try:
        text = repr(value)
    except Exception as e:  # a broken __repr__ must not lose the run
        text = f'<unrepresentable {type(value).__name__}: {e}>'
    _emit('text/plain', _clip(text, MAX_REPR))


namespace['display'] = display


async def run_cell(code):
    """Run one cell; returns True on success. Errors go to stderr as a short traceback."""
    try:
        result = await eval_code_async(code, globals=namespace, filename='<cell>')
        if result is not None and not (code.rstrip().endswith(';')):
            # a matplotlib artist list (from a bare ax.plot(...)) is noise; its figure is shown below
            if not (isinstance(result, list) and result and
                    (type(result[0]).__module__ or '').startswith('matplotlib')):
                _show(result)
            namespace['_'] = result
        _flush_figures()
        return True
    except BaseException as e:  # KeyboardInterrupt (Stop) included
        import traceback
        tb = traceback.TracebackException.from_exception(e)
        # drop Pyodide's and the runner's own frames: start at the user's cell
        tb.stack = traceback.StackSummary.from_list(
            [f for f in tb.stack if not (f.filename.endswith('pg_runtime.py')
                                         or '/_pyodide/' in f.filename or '/pyodide/' in f.filename)])
        sys.stderr.write(''.join(tb.format()))
        try:
            _flush_figures()
        except Exception:
            pass
        return False

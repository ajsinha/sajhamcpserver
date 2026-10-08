"""A minimal MCP server over stdio for the agent's tests: one tool, ``echo``."""

import json
import sys

TOOLS = [{'name': 'echo', 'description': 'Echo the text back', 'annotations': {'readOnlyHint': True},
          'inputSchema': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}]

for line in sys.stdin:
    msg = json.loads(line)
    if 'id' not in msg:
        continue
    m = msg.get('method')
    if m == 'initialize':
        out = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}}, 'serverInfo': {'name': 'echo', 'version': '1'}}
    elif m == 'tools/list':
        out = {'tools': TOOLS}
    elif m == 'tools/call':
        out = {'content': [{'type': 'text', 'text': 'echo: ' + str(msg['params']['arguments'].get('text'))}]}
    else:
        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'error': {'code': -32601, 'message': m}}) + '\n')
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': out}) + '\n')
    sys.stdout.flush()

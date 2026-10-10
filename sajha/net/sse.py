"""
Server-sent events for a streamed forwarded call (SAJHA Net §8.9, §15.10): the encoder a host writes
with, and the incremental parser a home reads with, bounded by line, event and stream sizes. No
dependency beyond the standard library.

Only what a net stream uses: ``data:`` lines (one JSON message per event, on one line), comment
lines (``: hb``, the heartbeat, which carries nothing), and the field names of the format (``event``,
``id``, ``retry``), which are accepted and ignored.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

HEARTBEAT = b': hb\n\n'
CONTENT_TYPE = 'text/event-stream'


def encode(message: Dict[str, Any]) -> bytes:
    """One event carrying ``message`` as compact JSON (JSON escapes newlines, so it is one data line)."""
    return b'data: ' + json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8') + b'\n\n'


class StreamLimit(Exception):
    """The stream broke a size limit (``what``: line, event or stream)."""

    def __init__(self, what: str):
        super().__init__(f'the stream exceeds its {what} limit')
        self.what = what


class Parser:
    """Feed bytes as they arrive; get back complete items, ``('event', data)`` or ``('comment', text)``.

    ``max_event_bytes`` bounds one event (its data lines together) and one line; ``max_stream_bytes`` the
    whole stream. A limit broken raises :class:`StreamLimit`; the parser is then unusable."""

    def __init__(self, max_event_bytes: int = 64 * 1024, max_stream_bytes: int = 8 * 1024 * 1024):
        self.max_event = int(max_event_bytes)
        self.max_stream = int(max_stream_bytes)
        self.total = 0
        self._buf = bytearray()
        self._data: List[bytes] = []
        self._size = 0
        self._broken = False
        self._skip_lf = False

    def feed(self, chunk: bytes) -> List[Tuple[str, str]]:
        if self._broken:
            raise StreamLimit('stream')
        self.total += len(chunk)
        if self.total > self.max_stream:
            self._broken = True
            raise StreamLimit('stream')
        out: List[Tuple[str, str]] = []
        buf = self._buf
        buf.extend(chunk)
        start = 0
        n = len(buf)
        i = 0
        while i < n:
            b = buf[i]
            if b == 0x0A and self._skip_lf and i == start:     # the \n of a \r\n split across chunks
                self._skip_lf = False
                start = i = i + 1
                continue
            self._skip_lf = False
            if b in (0x0A, 0x0D):
                line = bytes(buf[start:i])
                if b == 0x0D:
                    if i + 1 < n:
                        if buf[i + 1] == 0x0A:
                            i += 1
                    else:
                        self._skip_lf = True
                start = i = i + 1
                self._line(line, out)
                continue
            i += 1
        del buf[:start]
        if len(buf) > self.max_event:
            self._broken = True
            raise StreamLimit('line')
        return out

    def _line(self, line: bytes, out: List[Tuple[str, str]]) -> None:
        if not line:
            if self._data:
                data = b'\n'.join(self._data)
                self._data, self._size = [], 0
                out.append(('event', data.decode('utf-8', 'replace')))
            return
        if line.startswith(b':'):
            out.append(('comment', line[1:].strip().decode('utf-8', 'replace')))
            return
        name, sep, value = line.partition(b':')
        if sep and value.startswith(b' '):
            value = value[1:]
        if name == b'data':
            self._size += len(value) + 1
            if self._size > self.max_event:
                self._broken = True
                raise StreamLimit('event')
            self._data.append(value)
        # event, id, retry and unknown fields carry nothing a net stream uses

    @property
    def pending(self) -> bool:
        """True while an event has started but not ended (a stream that stops here is truncated)."""
        return bool(self._data) or bool(self._buf)


def parse_all(raw: bytes, **limits: Any) -> List[Tuple[str, str]]:
    """Every item of a whole stream body (tests, buffered transports)."""
    p = Parser(**limits)
    return p.feed(raw) + p.feed(b'\n\n') if not raw.endswith(b'\n\n') else p.feed(raw)


def loads_event(data: str) -> Optional[Dict[str, Any]]:
    try:
        v = json.loads(data)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None

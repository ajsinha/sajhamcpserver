"""
Redis state store (``state.backend: redis``): shared by every worker and host.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* key/value  -> Redis strings holding JSON, TTL as PX
* update     -> WATCH / MULTI optimistic transaction (retried)
* incr       -> INCRBYFLOAT in a Lua script that sets the TTL on creation
* windows    -> one sorted set per key (score = time), trimmed in Lua
* pub/sub    -> PUBLISH on ``<prefix>chan:<channel>``; one background thread
                per process listens on the pattern ``<prefix>chan:*`` and
                dispatches to the local handlers (reconnects on failure)

Requires the optional ``redis`` package (``pip install "redis>=5"``).
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from sajha.core.state.base import MessageHandler, StateStore, dumps, loads

logger = logging.getLogger(__name__)

_INCR = """
local v = redis.call('INCRBYFLOAT', KEYS[1], ARGV[1])
if tonumber(ARGV[2]) > 0 and redis.call('PTTL', KEYS[1]) == -1 then
  redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return v
"""

_WINDOW_ADD = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local n = redis.call('ZCARD', KEYS[1])
if limit >= 0 and n >= limit then
  return {0, n}
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000))
return {1, n + 1}
"""

_WINDOW_COUNT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[2]))
return redis.call('ZCARD', KEYS[1])
"""

_GLOB = re.compile(r"([*?\[\]\\])")


def _num(raw: Any) -> float:
    f = float(raw)
    return int(f) if f.is_integer() else f


def _px(ttl: Optional[float]) -> Optional[int]:
    return max(1, int(ttl * 1000)) if ttl is not None else None


class RedisStateStore(StateStore):
    backend = "redis"
    shared = True

    def __init__(self, url: str, prefix: str = "sajha:", client: Any = None):
        super().__init__(prefix)
        if client is None:
            try:
                import redis
            except ImportError as e:
                raise RuntimeError('state.backend is "redis" but the redis package is not installed: '
                                   'pip install "redis>=5"') from e
            client = redis.Redis.from_url(url, decode_responses=True, health_check_interval=30)
        self.url = url
        self.r = client
        self._incr = self.r.register_script(_INCR)
        self._wadd = self.r.register_script(_WINDOW_ADD)
        self._wcount = self.r.register_script(_WINDOW_COUNT)
        self._handlers: Dict[str, List[MessageHandler]] = {}
        self._hlock = threading.Lock()
        self._listener: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ready = threading.Event()

    # -- key/value -----------------------------------------------------------

    def get(self, key: str) -> Any:
        try:
            return loads(self.r.get(self.k(key)))
        except Exception as e:
            if e.__class__.__name__ == "ResponseError":   # WRONGTYPE: a window key
                return None
            raise

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self.r.set(self.k(key), dumps(value), px=_px(ttl))

    def add(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        return bool(self.r.set(self.k(key), dumps(value), px=_px(ttl), nx=True))

    def pop(self, key: str) -> Any:
        pipe = self.r.pipeline(transaction=True)
        pipe.get(self.k(key))
        pipe.delete(self.k(key))
        raw, _ = pipe.execute()
        return loads(raw)

    def delete(self, key: str) -> bool:
        return bool(self.r.delete(self.k(key)))

    def update(self, key: str, fn: Callable[[Any], Any], ttl: Optional[float] = None) -> Any:
        from redis.exceptions import WatchError
        full = self.k(key)
        for _ in range(100):
            with self.r.pipeline(transaction=True) as pipe:
                try:
                    pipe.watch(full)
                    current = loads(pipe.get(full))
                    new = fn(current)
                    keep_ms = None
                    if new is not None and ttl is None and current is not None:
                        pttl = pipe.pttl(full)
                        keep_ms = pttl if pttl and pttl > 0 else None
                    pipe.multi()
                    if new is None:
                        pipe.delete(full)
                    else:
                        pipe.set(full, dumps(new), px=_px(ttl) if ttl is not None else keep_ms)
                    pipe.execute()
                    return loads(dumps(new)) if new is not None else None
                except WatchError:
                    time.sleep(0.001)
                    continue
        raise RuntimeError(f"state update of {key!r} kept conflicting; gave up")

    def incr(self, key: str, amount: float = 1, ttl: Optional[float] = None) -> float:
        return _num(self._incr(keys=[self.k(key)], args=[repr(float(amount)), _px(ttl) or 0]))

    def scan(self, prefix: str) -> Iterator[Tuple[str, Any]]:
        pattern = _GLOB.sub(r"\\\1", self.k(prefix)) + "*"
        cut = len(self.prefix)
        batch: List[str] = []

        def flush():
            if not batch:
                return []
            values = self.r.mget(batch)
            out = [(k[cut:], loads(v)) for k, v in zip(batch, values) if v is not None]
            batch.clear()
            return out

        for full in self.r.scan_iter(match=pattern, count=500, _type="STRING"):
            batch.append(full)
            if len(batch) >= 200:
                yield from flush()
        yield from flush()

    def delete_prefix(self, prefix: str) -> int:
        pattern = _GLOB.sub(r"\\\1", self.k(prefix)) + "*"
        keys = list(self.r.scan_iter(match=pattern, count=500))
        n = 0
        for i in range(0, len(keys), 500):
            n += self.r.delete(*keys[i:i + 500])
        return n

    # -- windows -------------------------------------------------------------

    def window_add(self, key: str, window: float, limit: Optional[int] = None) -> Tuple[bool, int]:
        ok, n = self._wadd(keys=[self.k(key)],
                           args=[repr(time.time()), repr(float(window)), -1 if limit is None else int(limit),
                                 uuid.uuid4().hex])
        return bool(int(ok)), int(n)

    def window_count(self, key: str, window: float) -> int:
        return int(self._wcount(keys=[self.k(key)], args=[repr(time.time()), repr(float(window))]))

    # -- pub/sub -------------------------------------------------------------

    def _chan(self, channel: str) -> str:
        return f"{self.prefix}chan:{channel}"

    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        self.r.publish(self._chan(channel), dumps(message))

    def subscribe(self, channel: str, handler: MessageHandler) -> Callable[[], None]:
        with self._hlock:
            self._handlers.setdefault(channel, []).append(handler)
            if self._listener is None:
                self._listener = threading.Thread(target=self._listen, name="sajha-state-redis-pubsub",
                                                  daemon=True)
                self._listener.start()
        self._ready.wait(5)

        def unsubscribe() -> None:
            with self._hlock:
                lst = self._handlers.get(channel, [])
                if handler in lst:
                    lst.remove(handler)
        return unsubscribe

    def _listen(self) -> None:
        cut = len(self._chan(""))
        pattern = _GLOB.sub(r"\\\1", self._chan("")) + "*"
        backoff = 0.5
        while not self._stop.is_set():
            pubsub = None
            try:
                pubsub = self.r.pubsub()
                pubsub.psubscribe(pattern)
                backoff = 0.5
                while not self._stop.is_set():
                    m = pubsub.get_message(timeout=1.0)
                    if m and m.get("type") == "psubscribe":
                        self._ready.set()       # subscribed: publishes from now on reach us
                        continue
                    if not m or m.get("type") != "pmessage":
                        continue
                    channel = m["channel"][cut:]
                    try:
                        payload = loads(m["data"])
                    except ValueError:
                        continue
                    with self._hlock:
                        handlers = list(self._handlers.get(channel, ()))
                    for h in handlers:
                        try:
                            h(payload)
                        except Exception as e:
                            logger.warning(f"state handler on {channel} failed: {e}")
            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning(f"Redis pub/sub connection lost ({e}); reconnecting in {backoff:.1f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 10)
            finally:
                try:
                    if pubsub is not None:
                        pubsub.close()
                except Exception:
                    pass

    # -- lifecycle -----------------------------------------------------------

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except Exception:
            return False

    def describe(self) -> Dict[str, Any]:
        d = super().describe()
        d["url"] = _redact(self.url)
        d["reachable"] = self.ping()
        return d

    def close(self) -> None:
        self._stop.set()
        try:
            self.r.close()
        except Exception:
            pass


def _redact(url: str) -> str:
    """redis://user:secret@host -> redis://user:***@host"""
    return re.sub(r"(//[^:/@]*:)[^@]*@", r"\1***@", url or "")

"""Unauthenticated read-only BingX perpetual swap market data client.

Only official /quote public methods are used. No private/trading operations.
"""
import asyncio
import hashlib
import json
import logging
import time
from typing import Any
import httpx
from . import config

log = logging.getLogger(__name__)


class MarketDataError(Exception):
    pass


class BingX:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=10, headers={'User-Agent': 'BingX-Signals-ReadOnly/1.0'})
        self.cache: dict[str, tuple[float, Any]] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.limit = asyncio.Semaphore(4)
        self.endpoint_locks: dict[str, asyncio.Lock] = {}
        self.last_endpoint_call: dict[str, float] = {}
        self.redis = None
        if config.REDIS_URL:
            try:
                import redis.asyncio as redis
                self.redis = redis.from_url(config.REDIS_URL, decode_responses=True)
            except Exception:
                log.exception('Redis initialization failed; using memory cache')

    async def close(self):
        await self.client.aclose()
        if self.redis:
            await self.redis.aclose()

    async def query(self, path: str, params: dict | None = None, ttl: int = 10) -> Any:
        p = params or {}
        key = path + ':' + json.dumps(p, sort_keys=True)
        redis_key = 'bingx:public:' + hashlib.sha256(key.encode()).hexdigest()
        cached = self.cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        if self.redis:
            try:
                remote = await self.redis.get(redis_key)
                if remote is not None:
                    parsed = json.loads(remote)
                    self.cache[key] = (time.monotonic() + min(ttl, 10), parsed)
                    return parsed
            except Exception:
                log.warning('Redis cache unavailable, continuing with memory cache')
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self.cache.get(key)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            async with self.limit:
                # Conservative per-endpoint pacing: provider rules can be stricter
                # than the global IP limit, especially for candle endpoints.
                endpoint_lock = self.endpoint_locks.setdefault(path, asyncio.Lock())
                async with endpoint_lock:
                    elapsed = time.monotonic() - self.last_endpoint_call.get(path, 0)
                    if elapsed < 1.05:
                        await asyncio.sleep(1.05 - elapsed)
                    self.last_endpoint_call[path] = time.monotonic()
                for i, base in enumerate((config.BINGX_BASE_URL, config.BINGX_FALLBACK_URL)):
                    try:
                        r = await self.client.get(base + path, params=p)
                        r.raise_for_status()
                        data = r.json()
                        if not isinstance(data, dict) or str(data.get('code', '0')) != '0':
                            raise MarketDataError('Биржа отклонила запрос: ' + str(data.get('msg', 'unknown'))[:160])
                        # Prune unbounded cache, retain fresh entries only.
                        if len(self.cache) > 600:
                            now = time.monotonic()
                            self.cache = {k: v for k, v in self.cache.items() if v[0] > now}
                        self.cache[key] = (time.monotonic() + ttl, data.get('data'))
                        if self.redis:
                            try:
                                await self.redis.setex(redis_key, max(1, ttl), json.dumps(data.get('data')))
                            except Exception:
                                log.warning('Redis write failed; using memory cache')
                        return data.get('data')
                    except (httpx.ConnectError, httpx.TimeoutException) as exc:
                        log.warning('BingX connection error (%s): %s', base, exc)
                        if i == 1:
                            raise MarketDataError('BingX недоступен. Попробуйте позже.') from exc
                    except (httpx.HTTPStatusError, ValueError) as exc:
                        raise MarketDataError('Ошибка ответа BingX: ' + str(exc)[:100]) from exc
        raise MarketDataError('Нет данных биржи')

    async def contracts(self) -> list[dict]:
        raw = await self.query('/openApi/swap/v2/quote/contracts', ttl=1800)
        return raw if isinstance(raw, list) else []

    async def symbols(self) -> list[str]:
        contracts = await self.contracts()
        valid = []
        for entry in contracts:
            sym = str(entry.get('symbol', '')).upper()
            if sym.endswith('-USDT') and entry.get('status', 1) not in (0, '0', 'OFFLINE'):
                valid.append(sym)
        return sorted(set(valid))

    async def ticker(self, symbol: str | None = None) -> list[dict]:
        params = {'symbol': symbol} if symbol else {}
        raw = await self.query('/openApi/swap/v2/quote/ticker', params, ttl=10)
        return raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])

    async def candles(self, symbol: str, interval: str, limit: int = 310) -> list[dict]:
        raw = await self.query('/openApi/swap/v3/quote/klines', {'symbol': symbol, 'interval': interval, 'limit': limit}, ttl=8)
        result = []
        for item in raw or []:
            try:
                if isinstance(item, list):
                    t, o, h, l, c, v = item[:6]
                    close_time = int(item[6]) if len(item) > 6 else 0
                else:
                    t = item.get('time', item.get('openTime'))
                    o, h, l, c, v = (item[x] for x in ('open', 'high', 'low', 'close', 'volume'))
                    close_time = int(item.get('closeTime') or 0)
                candle = {'time': int(t), 'open': float(o), 'high': float(h), 'low': float(l), 'close': float(c), 'volume': float(v), 'closeTime': close_time}
                if candle['low'] > 0 and candle['low'] <= min(candle['open'], candle['close']) and candle['high'] >= max(candle['open'], candle['close']):
                    result.append(candle)
            except (ValueError, TypeError, KeyError, IndexError):
                continue
        return sorted({r['time']: r for r in result}.values(), key=lambda x: x['time'])

    async def extras(self, symbol: str) -> dict:
        endpoints = {
            'funding': ('/openApi/swap/v2/quote/fundingRate', {'symbol': symbol}),
            'openInterest': ('/openApi/swap/v2/quote/openInterest', {'symbol': symbol}),
            'depth': ('/openApi/swap/v2/quote/depth', {'symbol': symbol, 'limit': 20}),
        }
        async def grab(key, path, params):
            try:
                data = await self.query(path, params, ttl=30)
                if isinstance(data, list) and key == 'funding':
                    return data[-1] if data else None
                return data
            except MarketDataError:
                return None
        out = await asyncio.gather(*(grab(key, *args) for key, args in endpoints.items()))
        return dict(zip(endpoints, out))


def normalize_ticker(t: dict) -> dict:
    def fl(name, fallback=0):
        try:
            return float(t.get(name, fallback) or fallback)
        except (ValueError, TypeError):
            return float(fallback)
    return {
        'symbol': t.get('symbol', ''), 'lastPrice': fl('lastPrice'),
        'change24h': fl('priceChangePercent'), 'volume24h': fl('quoteVolume'),
        'high24h': fl('highPrice'), 'low24h': fl('lowPrice'),
        'time': int(t.get('closeTime') or time.time() * 1000),
    }

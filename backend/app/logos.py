"""Optional market-cap ranked cryptocurrency logos from CoinGecko.

No arbitrary URLs accepted from users. If this free endpoint is unavailable,
front-end falls back to a small curated public icon CDN and a graphic placeholder.
"""
import asyncio
import logging
import time
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)
_cache: dict[str, str] = {}
_expires: float = 0
_lock = asyncio.Lock()


def _safe_image(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == 'https' and parsed.hostname in {
        'coin-images.coingecko.com', 'assets.coingecko.com'
    }


def images_from_markets(pages: list[list[dict]]) -> dict[str, str]:
    """Select first (highest market-cap) image if tickers collide."""
    logos: dict[str, str] = {}
    for page in pages:
        for coin in page:
            symbol = str(coin.get('symbol') or '').upper()
            url = str(coin.get('image') or '')
            if 1 <= len(symbol) <= 18 and symbol.isalnum() and _safe_image(url):
                logos.setdefault(symbol, url)
    return logos


async def get_logos() -> dict[str, str]:
    global _cache, _expires
    if time.monotonic() < _expires:
        return _cache
    async with _lock:
        if time.monotonic() < _expires:
            return _cache
        try:
            async with httpx.AsyncClient(timeout=7.0, follow_redirects=False) as client:
                async def page(n: int):
                    resp = await client.get('https://api.coingecko.com/api/v3/coins/markets', params={
                        'vs_currency': 'usd', 'order': 'market_cap_desc', 'per_page': 250, 'page': n,
                        'sparkline': 'false'})
                    resp.raise_for_status()
                    data = resp.json()
                    return data if isinstance(data, list) else []
                pages = await asyncio.gather(page(1), page(2), page(3))
            logos = images_from_markets(pages)
            if logos:
                _cache = logos
                _expires = time.monotonic() + 12 * 3600
            else:
                _expires = time.monotonic() + 30 * 60
        except (httpx.HTTPError, ValueError, TypeError):
            log.warning('CoinGecko logo feed unavailable; using icon fallback', exc_info=False)
            _expires = time.monotonic() + 30 * 60
        return _cache

"""Fail-closed market eligibility for *automatic*, read-only BingX observations.

A 24h quoteVolume is not the same as base coin volume. We require USD(T)
turnover and a real launchTime from the perpetual-contract metadata. No
trading endpoints, private account credentials, or automatic orders are used.
"""
from __future__ import annotations

from collections import Counter
import re
import time
from typing import Any
from . import config
from .bingx import normalize_ticker

DAY_MS = 86_400_000
# Exchange-specific multiplier and leveraged token conventions. For unusual
# symbols, prefer false negatives to accidentally promoting synthetic pairs.
LEVERAGED_SUFFIX = re.compile(r'(?:[235][LS]|BULL|BEAR|DOWN)$')
MULTIPLIER_PREFIX = re.compile(r'^(?:\d{3,})[A-Z]')
VALID_SYMBOL = re.compile(r'^[A-Z0-9]{2,20}-USDT$')
# Known real assets with trailing digits may be added here after review.
TRAILING_DIGIT_EXCEPTIONS = frozenset({'1INCH', 'C98', 'L3', 'A8'})


def filter_settings() -> dict[str, Any]:
    return {
        'mode': config.MARKET_FILTER_MODE,
        'min24hTurnoverUSDT': config.MARKET_MIN_24H_USDT,
        'minListingAgeDays': config.MARKET_MIN_LISTING_DAYS,
        'excludeNonstandard': config.MARKET_EXCLUDE_NONSTANDARD,
        'ageSource': 'BingX perpetual contract launchTime',
        'failClosed': True,
    }


def _launch_ms(contract: dict) -> int | None:
    """Return reliable epoch milliseconds or None; never infer age from ticker."""
    try:
        stamp = int(contract.get('launchTime') or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    if 1_500_000_000 <= stamp <= 4_000_000_000:  # seconds timestamp
        stamp *= 1000
    if stamp < 1_500_000_000_000 or stamp > 4_000_000_000_000:
        return None
    return stamp


def _is_nonstandard(symbol: str) -> bool:
    if not VALID_SYMBOL.fullmatch(symbol):
        return True
    base = symbol[:-5]
    if (LEVERAGED_SUFFIX.search(base) or (len(base) >= 5 and base.endswith('UP'))
            or MULTIPLIER_PREFIX.match(base)):
        return True
    # Names such as NCSKABNB2 are excluded even if exchange exposes them.
    if base[-1].isdigit() and base not in TRAILING_DIGIT_EXCEPTIONS:
        return True
    return False


def _is_available(contract: dict, now_ms: int) -> bool:
    if contract.get('status', 1) in (0, '0', 'OFFLINE', 'offline', 'DISABLED'):
        return False
    if str(contract.get('apiStateClose', 'false')).lower() == 'true' and str(contract.get('apiStateOpen', 'true')).lower() == 'false':
        return False
    try:
        off_time = int(contract.get('offTime') or 0)
    except (ValueError, TypeError):
        return False
    if off_time and off_time <= now_ms:
        return False
    return True


def eligible_markets(contracts: list[dict], ticker_rows: list[dict], now_ms: int | None = None):
    """Return eligible symbol set and diagnostic counts without guessed inputs.

    Both background scanners call this function; no ticker volume or launch
    timestamp means exclusion, not an implicit free pass.
    """
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    tickers: dict[str, dict] = {}
    for row in ticker_rows:
        t = normalize_ticker(row)
        if t['symbol']:
            tickers[str(t['symbol']).upper()] = t
    accepted = set()
    reasons: Counter[str] = Counter()
    seen = set()
    for c in contracts:
        if not isinstance(c, dict):
            reasons['invalid_contract'] += 1
            continue
        sym = str(c.get('symbol', '')).upper()
        if not sym.endswith('-USDT') or sym in seen:
            continue
        seen.add(sym)
        if not _is_available(c, now_ms):
            reasons['inactive'] += 1
            continue
        if config.MARKET_EXCLUDE_NONSTANDARD and _is_nonstandard(sym):
            reasons['nonstandard'] += 1
            continue
        launch = _launch_ms(c)
        if launch is None:
            reasons['unknown_listing_date'] += 1
            continue
        if launch > now_ms or now_ms-launch < config.MARKET_MIN_LISTING_DAYS*DAY_MS:
            reasons['too_new'] += 1
            continue
        q = tickers.get(sym)
        if q is None or q['lastPrice'] <= 0 or q['volume24h'] < config.MARKET_MIN_24H_USDT:
            reasons['low_or_unknown_volume'] += 1
            continue
        accepted.add(sym)
    report = {
        **filter_settings(),
        'evaluated': len(seen),
        'eligible': len(accepted),
        'excluded': max(0, len(seen)-len(accepted)),
        'reasons': dict(reasons),
        'updatedAt': now_ms,
    }
    return accepted, report

"""All-market read-only rapid-move alerts. No exchange orders or trade suggestions.

A 5-minute price change from sampled all-market tickers is confirmed with
five *closed* 1-minute candles and a relative volume spike. Monitor starts
warming up after every server restart (no false events from 24h change).
"""
import asyncio
from collections import deque
import datetime as dt
import logging
import math
import time
from sqlalchemy import select, delete
from . import config, db, telegram
from .bingx import MarketDataError, normalize_ticker

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 300


def baseline_and_change(samples, now: float, current: float):
    """Use recent history only; never treat a day-long change as five minutes."""
    if not math.isfinite(current) or current <= 0:
        return None
    eligible = [(ts, price) for ts, price in samples if ts <= now - WINDOW_SECONDS]
    if not eligible:
        return None
    ts, baseline = eligible[-1]
    # Reject gaps and missing/old snapshots.
    if now - ts > WINDOW_SECONDS + 60 or baseline <= 0:
        return None
    change = (current / baseline - 1) * 100
    return baseline, change


def volume_confirmation(candles: list[dict], now_ms: int, min_turnover: float, factor: float):
    """Compare last five complete 1m bars with preceding four 5m blocks."""
    valid = [c for c in candles if c['time'] + 60_000 <= now_ms]
    valid.sort(key=lambda x: x['time'])
    if len(valid) < 25 or valid[-1]['time'] + 60_000 < now_ms - 120_000:
        return None
    recent, previous = valid[-5:], valid[-25:-5]
    last = valid[-25:]
    if any(b['time'] - a['time'] != 60_000 for a, b in zip(last, last[1:])):
        return None
    # OHLCV.volume is base-asset units; convert to approximate USDT turnover.
    def turn(items):
        return sum(max(0, c['volume']) * c['close'] for c in items)
    recent_value, preceding = turn(recent), turn(previous) / 4
    ratio = recent_value / preceding if preceding > 0 else 0
    if recent_value < min_turnover or ratio < factor:
        return None
    return round(ratio, 2), round(recent_value, 2)


class MoveMonitor:
    def __init__(self):
        self.history: dict[str, deque] = {}
        self.last_candidate_check: dict[str, float] = {}
        self.last_event: dict[tuple[str, str], float] = {}
        self.last_update: int | None = None
        self.last_error: str = ''
        self.started_at = time.time()
        self.observed = 0

    async def run_once(self, market, now: float | None = None) -> int:
        now = time.time() if now is None else now
        rows = [normalize_ticker(x) for x in await market.ticker()]
        processed = 0
        candidates = []
        # Snapshot ticker pricing for every active USDT pair with *one* public request.
        for tick in rows:
            symbol, price, volume24 = tick['symbol'], tick['lastPrice'], tick['volume24h']
            if not symbol.endswith('-USDT') or not price or not math.isfinite(price):
                continue
            processed += 1
            samples = self.history.setdefault(symbol, deque())
            movement = baseline_and_change(samples, now, price)
            if volume24 >= config.PUMP_MIN_24H_USDT and movement is not None:
                baseline, pct = movement
                if abs(pct) >= config.PUMP_THRESHOLD_PERCENT:
                    direction = 'PUMP' if pct > 0 else 'DUMP'
                    key = (symbol, direction)
                    # Same direction can't repeat too frequently, even when price oscillates.
                    if (now - self.last_event.get(key, 0) >= config.PUMP_COOLDOWN_MINUTES * 60
                        and now - self.last_candidate_check.get(symbol, 0) >= 65):
                        candidates.append((symbol, direction, baseline, price, pct))
                        self.last_candidate_check[symbol] = now
            if not samples or now - samples[-1][0] >= 10:
                samples.append((now, price))
            while samples and now - samples[0][0] > WINDOW_SECONDS + 60:
                samples.popleft()
        # Only query OHLCV for candidates. Avoid a second all-market scan.
        candidates.sort(key=lambda x: -abs(x[4]))
        created = 0
        for symbol, direction, baseline, price, pct in candidates[:15]:
            try:
                candles = await market.candles(symbol, '1m', 35)
                proof = volume_confirmation(candles, int(now * 1000),
                                            config.PUMP_MIN_TURNOVER_USDT, config.PUMP_VOLUME_MULTIPLIER)
                if proof is None:
                    continue
                with db.Session.begin() as session:
                    recent = session.scalar(select(db.PumpEvent).where(
                        db.PumpEvent.symbol == symbol, db.PumpEvent.direction == direction,
                        db.PumpEvent.occurred_at >= dt.datetime.fromtimestamp(
                            now - config.PUMP_COOLDOWN_MINUTES * 60, dt.timezone.utc)
                    ).order_by(db.PumpEvent.id.desc()).limit(1))
                    if recent:
                        self.last_event[(symbol, direction)] = now
                        continue
                    entry = db.PumpEvent(symbol=symbol, direction=direction,
                        change_pct=round(pct, 2), start_price=baseline, price=price,
                        volume_ratio=proof[0], turnover_usdt=proof[1])
                    session.add(entry)
                self.last_event[(symbol, direction)] = now
                created += 1
                await self._notify(symbol, direction, price, pct, proof)
                logger.info('Market movement %s %s: %.2f%% volume %.1fx', symbol, direction, pct, proof[0])
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Pump monitor: checking %s failed', symbol)
        # Keep in-memory rolling state bounded across delisted pairs.
        if len(self.history) > 3000:
            valid = {t['symbol'] for t in rows}
            self.history = {k: v for k, v in self.history.items() if k in valid}
        self.observed = processed
        self.last_update = int(now * 1000)
        self.last_error = ''
        return created

    async def _notify(self, symbol, direction, price, pct, proof):
        with db.Session() as session:
            subscribers = session.scalars(select(db.PumpSubscription).where(
                db.PumpSubscription.enabled.is_(True)).limit(1000)).all()
            chats = []
            for sub in subscribers:
                person = session.get(db.Person, sub.user_id)
                if person and person.chat_id and person.notifications:
                    chats.append(person.chat_id)
        emoji = '🟢' if direction == 'PUMP' else '🔴'
        message = (f'{emoji} {direction} · {symbol}\n'
                   f'Цена за ~5 минут: {pct:+.2f}%\n'
                   f'Последняя цена: {price:.9g} USDT\n'
                   f'Объём 5м: {proof[1]:,.0f} USDT · всплеск {proof[0]:.1f}×\n\n'
                   'Резкое движение уже произошло. Это наблюдение рынка, не призыв к сделке.')
        for chat in chats:
            await telegram.send_market(chat, message, symbol)

    async def loop(self, market):
        await asyncio.sleep(5)
        while True:
            try:
                if config.PUMP_MONITOR_ENABLED:
                    await self.run_once(market)
            except asyncio.CancelledError:
                raise
            except MarketDataError as e:
                self.last_error = str(e)
                logger.warning('Market movement monitor unavailable: %s', e)
            except Exception as e:
                self.last_error = str(e)
                logger.exception('Market movement monitor failed')
            await asyncio.sleep(config.PUMP_POLL_SECONDS)

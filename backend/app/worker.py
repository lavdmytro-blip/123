"""Best-effort persisted signal tracking, crossing alerts and watched-signal notifications.

One Railway replica only. In production for larger audiences use a dedicated worker
and a distributed lock; notifications never claim execution on an exchange.
"""
import asyncio
import datetime as dt
import json
import logging
import time
from sqlalchemy import select
from . import db, telegram, config
from .analysis import analyze
from .bingx import normalize_ticker, MarketDataError

log = logging.getLogger(__name__)


def crossed(a: float, b: float, target: float) -> bool:
    return (a < target <= b) or (a > target >= b)


def _status_at_candle(signal, candle):
    if signal.side not in ('LONG', 'SHORT') or signal.stop is None:
        return None, 0
    lo, hi = candle['low'], candle['high']
    stop = lo <= signal.stop if signal.side == 'LONG' else hi >= signal.stop
    reached = signal.tp_reached
    for level in (signal.tp1, signal.tp2, signal.tp3)[reached:]:
        if level is None:
            break
        target = hi >= level if signal.side == 'LONG' else lo <= level
        if not target:
            break
        reached += 1
    if stop and reached > signal.tp_reached:
        return 'AMBIGUOUS', signal.tp_reached  # order cannot be proven within one minute
    if stop:
        return 'STOP', reached
    if reached == 3:
        return 'TP3', reached
    return None, reached


async def update_signals(market):
    with db.Session() as session:
        active = session.scalars(select(db.Signal).where(db.Signal.status == 'ACTIVE').limit(150)).all()
        # Snapshot ORM outside DB transaction; requery inside write transaction.
        jobs = [(s.id, s.symbol, int(s.created_at.replace(tzinfo=dt.timezone.utc).timestamp() * 1000) if s.created_at.tzinfo is None else int(s.created_at.timestamp() * 1000)) for s in active]
    symbols = sorted({sym for _, sym, _ in jobs})
    now_ms = int(time.time() * 1000)
    for symbol in symbols:
        try:
            candles = await market.candles(symbol, '1m', 300)
        except MarketDataError:
            continue
        closed = [c for c in candles if c['time'] + 60000 <= now_ms]
        with db.Session() as session:
            for item_id, _, created in (j for j in jobs if j[1] == symbol):
                s = session.get(db.Signal, item_id)
                if not s or s.status != 'ACTIVE':
                    continue
                previous_check = s.last_checked
                next_expected = max(((created + 59999) // 60000) * 60000,
                                    previous_check + 60000 if previous_check else 0)
                if closed and closed[0]['time'] > next_expected + 60000:
                    s.status = 'STALE'
                    person = session.get(db.Person, s.user_id)
                    if person and person.notifications and person.chat_id:
                        await telegram.send(person.chat_id, f'⏱ {s.symbol}: история для проверки сценария неполная. Статус STALE — исход неизвестен.')
                    continue
                for candle in closed:
                    # Drop the candle overlapping creation: could include pre-signal moves.
                    if candle['time'] < created or candle['time'] <= s.last_checked:
                        continue
                    status, reached = _status_at_candle(s, candle)
                    new_targets = list(range(s.tp_reached + 1, reached + 1))
                    s.tp_reached = reached
                    s.last_checked = candle['time']
                    person = session.get(db.Person, s.user_id)
                    if person and person.notifications and person.chat_id:
                        for level in new_targets:
                            if status != 'AMBIGUOUS':
                                await telegram.send(person.chat_id, f'🎯 {s.symbol} {s.side}: достигнут TP{level} (по минутной свече). Не исполнение сделки.')
                        if status == 'STOP':
                            await telegram.send(person.chat_id, f'🔴 {s.symbol} {s.side}: достигнут SL (по минутной свече).')
                        if status == 'AMBIGUOUS':
                            await telegram.send(person.chat_id, f'⚠️ {s.symbol}: TP и SL внутри одной минутной свечи; порядок не определить.')
                    if status:
                        s.status = status
                        break
            session.commit()


async def update_alerts(market):
    with db.Session() as session:
        alarms = session.scalars(select(db.Alert).where(db.Alert.active.is_(True)).limit(200)).all()
        targets = sorted({x.symbol for x in alarms})
    if not targets:
        return
    try:
        tickers = {t['symbol']: t for t in map(normalize_ticker, await market.ticker())}
    except MarketDataError:
        return
    with db.Session() as session:
        for alert in session.scalars(select(db.Alert).where(db.Alert.active.is_(True)).limit(200)):
            current = tickers.get(alert.symbol, {}).get('lastPrice')
            if not current:
                continue
            if crossed(alert.baseline_price, current, alert.target_price):
                alert.active = False
                person = session.get(db.Person, alert.user_id)
                if person and person.notifications and person.chat_id:
                    await telegram.send(person.chat_id, f'🔔 {alert.symbol}: цена пересекла заданный уровень {alert.target_price:.8g}. Текущая котировка: {current:.8g}.')
            else:
                alert.baseline_price = current
        session.commit()


async def update_watches(market):
    with db.Session() as session:
        watches = session.scalars(select(db.Watch).limit(config.MAX_SCAN_WATCHES)).all()
        jobs = [(x.id, x.symbol, x.interval) for x in watches]
    for watch_id, symbol, interval in jobs:
        try:
            candles = await market.candles(symbol, interval)
            result = analyze(symbol, interval, candles, None)
        except (MarketDataError, ValueError):
            continue
        with db.Session() as session:
            watch = session.get(db.Watch, watch_id)
            if not watch:
                continue
            if watch.last_side != result['side']:
                watch.last_side = result['side']
                person = session.get(db.Person, watch.user_id)
                if result['side'] != 'WAIT' and person and person.chat_id and person.notifications:
                    await telegram.send(person.chat_id, f'📡 {symbol} {interval}: появился технический сценарий {result["side"]}. Открой Mini App, чтобы проверить его актуальность и уровни.')
            session.commit()


async def loop(market):
    cycles = 0
    await asyncio.sleep(15)
    while True:
        try:
            await update_alerts(market)
            await update_signals(market)
            if cycles % 4 == 0:
                await update_watches(market)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Notification worker error')
        cycles += 1
        await asyncio.sleep(90)

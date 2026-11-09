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
from . import db, telegram, config, market_filter
from .analysis import analyze
from .ai import ai_comment
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


def _created_ms(item) -> int:
    return int(item.created_at.replace(tzinfo=dt.timezone.utc).timestamp() * 1000) if item.created_at.tzinfo is None else int(item.created_at.timestamp() * 1000)


POPULAR_MARKETS = ('BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'BNB-USDT', 'DOGE-USDT',
                   'ADA-USDT', 'AVAX-USDT', 'TON-USDT', 'LINK-USDT', 'DOT-USDT', 'TRX-USDT')


def ordered_universe(available: list[str], tickers: list[dict]) -> list[str]:
    """One full rotation over every valid symbol; large/liquid assets are visited first."""
    symbols = set(available)
    if config.AUTO_SIGNALS_UNIVERSE == 'CUSTOM':
        symbols.intersection_update(config.AUTO_SIGNALS_SYMBOLS)
    scores = {t['symbol']: t.get('volume24h', 0) for t in tickers}
    preferred = {v: i for i, v in enumerate(POPULAR_MARKETS)}
    # Sort fixed top symbols first, then rest in volume order, then symbol for stability.
    return sorted(symbols, key=lambda s: (0, preferred[s]) if s in preferred else
                  (1, -scores.get(s, 0), s))


def _set_scan_progress(*, total=None, scanned=None, last_symbol=None, completed=False, error=None):
    with db.Session.begin() as session:
        state = session.get(db.ScannerState, 1)
        if not state:
            state = db.ScannerState(id=1)
            session.add(state)
        if total is not None:
            state.total = total
        if scanned is not None:
            state.scanned = scanned
        if last_symbol is not None:
            state.last_symbol = last_symbol
        if error is not None:
            state.error = str(error)[:200]
        state.updated_at = db.now()
        if completed:
            state.round += 1
            state.last_completed_at = db.now()


async def _scan_one(market, symbol: str, interval: str, live: float, now_ms: int):
    """Evaluate just-closed bars; return true only if a paper scenario was published."""
    step_ms = config.INTERVALS[interval] * 1000
    candles = await market.candles(symbol, interval)
    closed = [c for c in candles if c['time'] + step_ms <= now_ms]
    if len(closed) < 210:
        return False
    last_bar = closed[-1]['time']
    # Do not publish old signals if the exchange has stopped sending fresh candles.
    if now_ms - (last_bar + step_ms) > step_ms + 30_000:
        return False
    with db.Session() as session:
        previous = session.scalars(select(db.AutoSignal).where(
            db.AutoSignal.symbol == symbol, db.AutoSignal.interval == interval
        ).order_by(db.AutoSignal.id.desc()).limit(1)).first()
        if previous and (previous.candle_time == last_bar or
                         (now_ms - _created_ms(previous) < 90 * 60_000) or
                         previous.status == 'ACTIVE'):
            return False
    result = analyze(symbol, interval, closed, None, now_ms)
    if result['side'] not in ('LONG', 'SHORT') or not result['takeProfits'] or result['entry'] is None:
        return False
    atr = result['metrics'].get('atr') or 0
    # A stale entry area must never be shown as if it were currently attainable.
    if not live or abs(live - result['entry']) > max(result['entry'] * 0.002, atr * 0.4):
        return False
    if config.OPENAI_API_KEY:
        result['aiSummary'] = await ai_comment(result)
    with db.Session.begin() as session:
        sig = db.AutoSignal(symbol=symbol, interval=interval, side=result['side'],
            entry=result['entry'], stop=result['stopLoss'],
            tp1=result['takeProfits'][0], tp2=result['takeProfits'][1], tp3=result['takeProfits'][2],
            candle_time=last_bar, result_json=json.dumps(result, ensure_ascii=False))
        session.add(sig)
        session.flush()
        new_id = sig.id
    log.info('Paper scenario #%s published for %s %s', new_id, symbol, interval)
    with db.Session() as session:
        subscribers = session.scalars(select(db.AutoSignalSubscription).where(
            db.AutoSignalSubscription.enabled.is_(True)).limit(100)).all()
        chats = []
        for sub in subscribers:
            person = session.get(db.Person, sub.user_id)
            if person and person.chat_id and person.notifications:
                chats.append(person.chat_id)
    # Network sends should not block the market rotation for too long.
    for chat_id in chats:
        await telegram.send_market(chat_id, f'📡 Аналитический сценарий · {symbol} ({interval})\n'
            f'Направление: {result["side"]}\n'
            f'Entry: {result["entry"]:.9g} · SL: {result["stopLoss"]:.9g}\n'
            f'TP1: {result["takeProfits"][0]:.9g}\n'
            f'TP2: {result["takeProfits"][1]:.9g}\n'
            f'TP3: {result["takeProfits"][2]:.9g}\n'
            'Виртуальный сценарий, не сделка и не прогноз с гарантией.', symbol)
    return True


async def auto_scan(market, *, max_symbols: int | None = None):
    """One sweep of the entire public USDT perpetual universe, in paced batches.

    This runs independently of status tracking so an extended sweep never blocks
    1-minute TP/SL updates. max_symbols is used only in offline tests.
    """
    if not config.AUTO_SIGNALS_ENABLED:
        return 0
    interval = config.AUTO_SIGNALS_INTERVAL
    if interval not in config.INTERVALS:
        log.error('Invalid auto scan interval %s', interval)
        return 0
    # Contract launchTime + USDT quoteVolume are mandatory for automatic signals.
    # Missing data must not accidentally promote a new or obscure pair.
    contracts = await market.contracts()
    ticker_rows = await market.ticker()
    allowed, eligibility = market_filter.eligible_markets(contracts, ticker_rows)
    quotes = {t['symbol']: t for t in map(normalize_ticker, ticker_rows)}
    rotation = ordered_universe(sorted(allowed), list(quotes.values()))
    log.info('Balanced filter: %s/%s eligible; excluded %s',
             eligibility['eligible'], eligibility['evaluated'], eligibility['reasons'])
    total = len(rotation)
    if max_symbols is not None:
        rotation = rotation[:max_symbols]
    _set_scan_progress(total=total, scanned=0, error='')
    processed = 0
    for i, symbol in enumerate(rotation, 1):
        try:
            now_ms = int(time.time() * 1000)
            live = quotes.get(symbol, {}).get('lastPrice', 0)
            await _scan_one(market, symbol, interval, live, now_ms)
        except asyncio.CancelledError:
            raise
        except MarketDataError as exc:
            log.warning('Scan of %s failed: %s', symbol, exc)
        except Exception:
            log.exception('Auto scan failed for %s', symbol)
        processed = i
        if i % config.AUTO_SCAN_BATCH_SIZE == 0 or i == len(rotation):
            _set_scan_progress(scanned=i, last_symbol=symbol)
            # Refresh price snapshot between batches, not for every coin.
            try:
                quotes = {t['symbol']: t for t in map(normalize_ticker, await market.ticker())}
            except MarketDataError:
                pass
        if i < len(rotation):
            await asyncio.sleep(config.AUTO_SCAN_PACE_SECONDS)
    if max_symbols is None:
        _set_scan_progress(scanned=total, completed=True)
    return processed


async def scanner_loop(market):
    """Dedicated scanner; no async starvation of the notification/status loop."""
    await asyncio.sleep(8)
    while True:
        try:
            if config.AUTO_SIGNALS_ENABLED:
                count = await auto_scan(market)
                log.info('Completed all-market scan (%d symbols)', count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception('All-market scan round failed')
            _set_scan_progress(error=str(exc))
        await asyncio.sleep(config.AUTO_SCAN_COOLDOWN_SECONDS)


async def update_auto_signals(market):
    now_ms = int(time.time() * 1000)
    with db.Session() as session:
        active = session.scalars(select(db.AutoSignal).where(db.AutoSignal.status == 'ACTIVE').limit(500)).all()
        jobs = [(x.id, x.symbol, _created_ms(x)) for x in active]
    notifications: list[tuple[str, str]] = []
    for symbol in sorted({x[1] for x in jobs}):
        try:
            candles = await market.candles(symbol, '1m', 300)
        except MarketDataError:
            continue
        closed = [c for c in candles if c['time'] + 60_000 <= now_ms]
        with db.Session.begin() as session:
            for item_id, _, created in (j for j in jobs if j[1] == symbol):
                sig = session.get(db.AutoSignal, item_id)
                if not sig or sig.status != 'ACTIVE':
                    continue
                # Missing minutes means we cannot reliably determine TP/SL order.
                needed = max(((created + 59999) // 60000) * 60000, sig.last_checked + 60000 if sig.last_checked else 0)
                if closed and closed[0]['time'] > needed + 60_000:
                    sig.status = 'STALE'
                    continue
                for candle in closed:
                    if candle['time'] < created or candle['time'] <= sig.last_checked:
                        continue
                    if sig.last_checked and candle['time'] > sig.last_checked + 60_000:
                        sig.status = 'STALE'
                        break
                    status, reached = _status_at_candle(sig, candle)
                    sig.tp_reached = reached
                    sig.last_checked = candle['time']
                    if status:
                        sig.status = status
                        break
                if sig.status == 'ACTIVE' and now_ms - created > 24 * 3600_000:
                    sig.status = 'EXPIRED'
                # Preserve exactly one notification per new milestone after persistence.
                if sig.status != 'ACTIVE' or sig.tp_reached:
                    previous = next((x for x in active if x.id == item_id), None)
                    if previous and (previous.status != sig.status or previous.tp_reached != sig.tp_reached):
                        status_text = (f'TP{sig.tp_reached} достигнут' if sig.status == 'ACTIVE'
                                       else f'Итог: {sig.status}' + (f' · достигнуто TP{sig.tp_reached}' if sig.tp_reached else ''))
                        notifications.append((sig.symbol, f'📊 {sig.symbol} {sig.side} · {status_text}\n'
                                              f'Цена входа: {sig.entry:.9g} · SL: {sig.stop:.9g}\n'
                                              'Проверено по закрытым минутным свечам, не исполненная сделка.'))
    if notifications:
        # Existing pre-filter scenarios may still be monitored for audit, but
        # must not generate new Telegram notifications for excluded symbols.
        try:
            contracts, raw_tickers = await asyncio.gather(market.contracts(), market.ticker())
            allowed, _ = market_filter.eligible_markets(contracts, raw_tickers)
        except MarketDataError:
            allowed = set()  # fail closed when qualification cannot be checked
        notifications = [(sym, msg) for sym, msg in notifications if sym in allowed]
    if notifications:
        with db.Session() as session:
            subs = session.scalars(select(db.AutoSignalSubscription).where(
                db.AutoSignalSubscription.enabled.is_(True)).limit(1000)).all()
            chats = []
            for sub in subs:
                person = session.get(db.Person, sub.user_id)
                if person and person.chat_id and person.notifications:
                    chats.append(person.chat_id)
        for symbol, message in notifications:
            for chat_id in chats:
                await telegram.send_market(chat_id, message, symbol)


async def loop(market):
    cycles = 0
    await asyncio.sleep(15)
    while True:
        try:
            await update_alerts(market)
            await update_signals(market)
            if config.AUTO_SIGNALS_ENABLED:
                await update_auto_signals(market)
            if cycles % 4 == 0:
                await update_watches(market)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Notification worker error')
        cycles += 1
        await asyncio.sleep(90)

import asyncio
import contextlib
import datetime as dt
import json
import logging
import math
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete, func
from . import config, db, telegram, worker, logos, market_moves, market_filter
from .analysis import analyze
from .ai import ai_comment
from .auth import optional_user, require_user
from .bingx import BingX, MarketDataError, normalize_ticker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
market = BingX()
move_monitor = market_moves.MoveMonitor()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    await telegram.setup()
    task = asyncio.create_task(worker.loop(market)) if config.ENABLE_WORKER else None
    scan_task = asyncio.create_task(worker.scanner_loop(market)) if config.ENABLE_WORKER and config.AUTO_SIGNALS_ENABLED else None
    pump_task = asyncio.create_task(move_monitor.loop(market)) if config.ENABLE_WORKER and config.PUMP_MONITOR_ENABLED else None
    yield
    if pump_task:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
    if scan_task:
        scan_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await scan_task
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await market.close()


app = FastAPI(title='BingX AI Signals', version='1.3.3', lifespan=lifespan,
              docs_url=None, redoc_url=None)


@app.exception_handler(MarketDataError)
async def data_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=503)


def check_interval(interval: str):
    if interval not in config.INTERVALS:
        raise HTTPException(400, 'Недопустимый таймфрейм')
    return interval


async def check_symbol(symbol: str):
    symbol = symbol.strip().upper().replace('/', '-')
    if len(symbol) > 20 or not symbol.endswith('-USDT') or not symbol.replace('-', '').isalnum():
        raise HTTPException(400, 'Неверный символ')
    if symbol not in await market.symbols():
        raise HTTPException(404, 'Торговая пара не найдена на BingX')
    return symbol


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'mode': 'read-only', 'bot': bool(config.BOT_TOKEN)}


@app.get('/api/markets')
async def markets(search: str = ''):
    items = await market.symbols()
    needle = search.upper().strip().replace('/', '-')[:25]
    matching = [s for s in items if needle in s]
    return {'symbols': matching[:2500], 'total': len(matching), 'updatedFrom': 'BingX'}


@app.get('/api/coin-logos')
async def coin_logos():
    """Public, cached brand images; logo coverage varies by provider."""
    mapping = await logos.get_logos()
    return {'images': mapping, 'count': len(mapping), 'source': 'CoinGecko',
            'fallback': 'cryptocurrency-icons'}


@app.get('/api/tickers')
async def tickers():
    available = set(await market.symbols())
    tick = [normalize_ticker(t) for t in await market.ticker()]
    return {'tickers': [t for t in tick if t['symbol'] in available and t['lastPrice'] > 0], 'source': 'BingX',
            'updatedAt': __import__('time').time_ns() // 1000000}


@app.get('/api/sparklines')
async def sparklines(symbols: str = ''):
    requested = [s.strip().upper() for s in symbols.split(',') if s.strip()][:8]
    allowed = set(await market.symbols())
    requested = [s for s in requested if s in allowed]
    async def fetch(s):
        try:
            rows = await market.candles(s, '1h', 28)
            return s, [x['close'] for x in rows[-24:]]
        except MarketDataError:
            return s, []
    items = await asyncio.gather(*(fetch(s) for s in requested))
    return {'sparklines': dict(items)}


@app.get('/api/candles')
async def candles(symbol: str, interval: str = '15m'):
    sym = await check_symbol(symbol)
    check_interval(interval)
    data = await market.candles(sym, interval, 310)
    return {'symbol': sym, 'interval': interval, 'candles': data, 'source': 'BingX'}


class AnalyzeBody(BaseModel):
    symbol: str
    interval: str = '15m'
    save: bool = True


async def run_analysis(symbol: str, interval: str):
    s = await check_symbol(symbol)
    check_interval(interval)
    candles, extras = await asyncio.gather(market.candles(s, interval), market.extras(s))
    result = analyze(s, interval, candles, extras)
    if result['price'] is not None:
        result['aiSummary'] = await ai_comment(result)
    if result['price'] is None:
        return result
    return result


@app.post('/api/analyze')
async def analysis(body: AnalyzeBody, user_id: int | None = Depends(optional_user)):
    result = await run_analysis(body.symbol, body.interval)
    if user_id and body.save and result['price'] is not None:
        with db.Session.begin() as session:
            db.get_person(session, user_id)
            t = result['takeProfits']
            rec = db.Signal(user_id=user_id, symbol=result['symbol'], interval=result['interval'],
                            side=result['side'], entry=result['entry'], stop=result['stopLoss'],
                            tp1=t[0] if t else None, tp2=t[1] if t else None, tp3=t[2] if t else None,
                            status='ACTIVE' if result['side'] != 'WAIT' else 'WAIT', result_json=json.dumps(result))
            session.add(rec)
    return result


async def eligible_snapshot():
    """Market eligibility is always computed from fresh-enough public API data."""
    contracts, tickers = await asyncio.gather(market.contracts(), market.ticker())
    allowed, report = market_filter.eligible_markets(contracts, tickers)
    return allowed, report, {t['symbol']: t for t in map(normalize_ticker, tickers)}


@app.get('/api/market-filter')
async def market_filter_status():
    """Public read-only diagnostics; exposes no accounts or private API keys."""
    _, report, _ = await eligible_snapshot()
    return report


@app.get('/api/auto-signals')
async def auto_signals(user_id: int | None = Depends(optional_user)):
    """Public feed, with per-user opt-in flag (no private account data exposed)."""
    with db.Session() as session:
        rows = session.scalars(select(db.AutoSignal).order_by(db.AutoSignal.id.desc()).limit(80)).all()
        sub = session.get(db.AutoSignalSubscription, user_id) if user_id else None
        subscribed = bool(sub and sub.enabled)
        state = session.get(db.ScannerState, 1)
        scanner = {'total': state.total, 'scanned': state.scanned, 'round': state.round,
                   'lastSymbol': state.last_symbol, 'lastUpdate': state.updated_at.isoformat() if state.updated_at else None,
                   'lastCompleted': state.last_completed_at.isoformat() if state.last_completed_at else None,
                   'error': state.error} if state else {'total': 0, 'scanned': 0, 'round': 0, 'lastSymbol': '', 'lastUpdate': None, 'lastCompleted': None, 'error': ''}
        feed = [db.auto_signal_out(x) for x in rows]
    try:
        allowed, filter_report, ticker_data = await eligible_snapshot()
        # Old excluded records are kept for audit, but not promoted to live feed.
        feed = [row for row in feed if row['symbol'] in allowed]
        live_prices = {row['symbol']: ticker_data[row['symbol']]['lastPrice'] for row in feed
                       if row['symbol'] in ticker_data and ticker_data[row['symbol']]['lastPrice'] > 0}
        prices_fresh = True
    except MarketDataError:
        # Fail closed: absence of a trustworthy universe cannot yield a new pick.
        feed, live_prices, prices_fresh = [], {}, False
        filter_report = {**market_filter.filter_settings(), 'error': 'BingX market data unavailable'}
    return {'signals': feed, 'prices': live_prices, 'pricesFresh': prices_fresh,
            'marketFilter': filter_report,
            'updatedAt': __import__('time').time_ns() // 1_000_000,
            'subscribed': subscribed, 'scannerEnabled': config.ENABLE_WORKER and config.AUTO_SIGNALS_ENABLED,
            'scanner': scanner, 'topSymbols': list(worker.POPULAR_MARKETS)}


# Archive is intentionally independent from the balanced market filter. Old outcomes
# remain available for auditing, including delisted and now-excluded symbols.
AUTO_HISTORY_STATES = {'ALL', 'ACTIVE', 'TP3', 'STOP', 'AMBIGUOUS', 'STALE', 'EXPIRED'}


@app.get('/api/auto-history')
async def auto_history(page: int = 1, page_size: int = 20, outcome: str = 'COMPLETED',
                       side: str = 'ALL', symbol: str = '', date_from: str = '', date_to: str = ''):
    """All persisted paper scenarios, paged and searchable (not actual executed orders)."""
    if not (1 <= page <= 100_000 and 1 <= page_size <= 50):
        raise HTTPException(422, 'Недопустимый размер страницы')
    outcome, side = outcome.upper(), side.upper()
    if outcome not in AUTO_HISTORY_STATES | {'COMPLETED'} or side not in {'ALL', 'LONG', 'SHORT'}:
        raise HTTPException(400, 'Недопустимый фильтр истории')
    sym = symbol.strip().upper().replace('/', '-').replace(' ', '')
    if len(sym) > 30 or (sym and not sym.replace('-', '').isalnum()):
        raise HTTPException(400, 'Неверный поиск монеты')
    try:
        start = dt.date.fromisoformat(date_from) if date_from else None
        end = dt.date.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(400, 'Дата должна быть YYYY-MM-DD')
    if start and end and start > end:
        raise HTTPException(400, 'Дата начала позже даты окончания')

    conditions = []
    if outcome == 'COMPLETED':
        conditions.append(db.AutoSignal.status != 'ACTIVE')
    elif outcome != 'ALL':
        conditions.append(db.AutoSignal.status == outcome)
    if side != 'ALL':
        conditions.append(db.AutoSignal.side == side)
    if sym:
        conditions.append(db.AutoSignal.symbol.contains(sym))
    if start:
        conditions.append(db.AutoSignal.created_at >= dt.datetime.combine(start, dt.time.min, dt.timezone.utc))
    if end:
        conditions.append(db.AutoSignal.created_at < dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, dt.timezone.utc))
    with db.Session() as session:
        query = select(db.AutoSignal).where(*conditions)
        total = session.scalar(select(func.count()).select_from(db.AutoSignal).where(*conditions)) or 0
        records = session.scalars(query.order_by(db.AutoSignal.id.desc()).offset((page-1)*page_size).limit(page_size)).all()
        counts = dict(session.execute(select(db.AutoSignal.status, func.count()).group_by(db.AutoSignal.status)).all())
        tp1 = session.scalar(select(func.count()).select_from(db.AutoSignal).where(db.AutoSignal.tp_reached >= 1)) or 0
        tp2 = session.scalar(select(func.count()).select_from(db.AutoSignal).where(db.AutoSignal.tp_reached >= 2)) or 0
        outputs = []
        for s in records:
            row = db.auto_signal_out(s)
            terminal = s.status != 'ACTIVE'
            legacy_finish = (dt.datetime.fromtimestamp((s.last_checked + 60_000)/1000, dt.timezone.utc)
                             if terminal and s.last_checked and s.status in ('STOP','TP3','AMBIGUOUS') else None)
            closed_at = s.finished_at or legacy_finish
            row['createdAt'] = s.created_at.replace(tzinfo=dt.timezone.utc).isoformat() if s.created_at.tzinfo is None else s.created_at.isoformat()
            row['finishedAt'] = (closed_at.replace(tzinfo=dt.timezone.utc).isoformat() if closed_at.tzinfo is None else closed_at.isoformat()) if closed_at else None
            row['finishedAtSource'] = ('recorded' if s.finished_at else 'last_checked_candle' if legacy_finish else 'unknown')
            # Hypothetical full-position movement to the terminating price level;
            # partial take-profit allocation/fees/slippage are unspecified.
            last_level = s.tp3 if s.status == 'TP3' else s.stop if s.status == 'STOP' else None
            row['terminalLevel'] = last_level
            row['terminalMovePercent'] = (round(100 * ((last_level / s.entry - 1) * (1 if s.side == 'LONG' else -1)), 3)
                                           if last_level and s.entry and s.entry > 0 else None)
            outputs.append(row)
    total_known = counts.get('TP3', 0) + counts.get('STOP', 0)
    return {'items': outputs, 'page': page, 'pageSize': page_size, 'total': total,
            'hasMore': page * page_size < total,
            'stats': {'total': sum(counts.values()), 'active': counts.get('ACTIVE', 0),
                      'tp1Reached': tp1, 'tp2Reached': tp2,
                      'tp3': counts.get('TP3', 0), 'stop': counts.get('STOP', 0),
                      'ambiguous': counts.get('AMBIGUOUS', 0), 'stale': counts.get('STALE', 0),
                      'expired': counts.get('EXPIRED', 0), 'knownOutcomes': total_known,
                      'tp3ShareOfKnownPercent': round(100 * counts.get('TP3', 0) / total_known, 1) if total_known else None},
            'disclaimer': 'Historical simulated scenarios; NOT executed trades. No assumed position size, leverage, fees or fills.'}


class AutoSubscriptionBody(BaseModel):
    enabled: bool


@app.post('/api/auto-subscription')
async def auto_subscription(body: AutoSubscriptionBody, user_id: int = Depends(require_user)):
    with db.Session.begin() as session:
        db.get_person(session, user_id)
        sub = session.get(db.AutoSignalSubscription, user_id)
        if not sub:
            session.add(db.AutoSignalSubscription(user_id=user_id, enabled=body.enabled))
        else:
            sub.enabled = body.enabled
    return {'enabled': body.enabled}


@app.get('/api/pump-events')
async def pump_events(user_id: int | None = Depends(optional_user)):
    """Public observed market movements; private notification preference per user."""
    with db.Session() as session:
        events = session.scalars(select(db.PumpEvent).order_by(db.PumpEvent.id.desc()).limit(100)).all()
        preference = session.get(db.PumpSubscription, user_id) if user_id else None
        subscribed = bool(preference and preference.enabled)
    try:
        allowed, filter_report, _ = await eligible_snapshot()
    except MarketDataError:
        allowed = set()
        filter_report = {**market_filter.filter_settings(), 'error': 'BingX market data unavailable'}
    # Archive is not deleted; old excluded symbols are simply hidden in the feed.
    events = [event for event in events if event.symbol in allowed]
    return {'events': [db.pump_event_out(event) for event in events],
            'marketFilter': filter_report,
            'subscribed': subscribed, 'monitorEnabled': config.ENABLE_WORKER and config.PUMP_MONITOR_ENABLED,
            'monitor': {'observed': move_monitor.observed, 'updatedAt': move_monitor.last_update,
                        'error': move_monitor.last_error, 'warmingUp': move_monitor.last_update is None
                        or int(__import__('time').time()) - int(move_monitor.started_at) < 300},
            'criteria': {'windowMinutes': 5, 'minChangePercent': config.PUMP_THRESHOLD_PERCENT,
                         'minVolumeRatio': config.PUMP_VOLUME_MULTIPLIER}}


class PumpSubscriptionBody(BaseModel):
    enabled: bool


@app.post('/api/pump-subscription')
async def pump_subscription(body: PumpSubscriptionBody, user_id: int = Depends(require_user)):
    with db.Session.begin() as session:
        person = db.get_person(session, user_id)
        if body.enabled and not person.chat_id:
            raise HTTPException(400, 'Сначала напиши /start в личном чате своего Telegram-бота')
        sub = session.get(db.PumpSubscription, user_id)
        if sub:
            sub.enabled = body.enabled
        else:
            session.add(db.PumpSubscription(user_id=user_id, enabled=body.enabled))
    return {'enabled': body.enabled}


@app.get('/api/me')
async def me(user_id: int = Depends(require_user)):
    with db.Session.begin() as session:
        p = db.get_person(session, user_id)
        return {'userId': p.user_id, 'language': p.language, 'theme': p.theme, 'interval': p.interval,
                'notifications': p.notifications, 'chatConnected': bool(p.chat_id)}


class SettingsBody(BaseModel):
    language: str = 'ru'
    theme: str = 'dark'
    interval: str = '15m'
    notifications: bool = True


@app.post('/api/settings')
async def settings(body: SettingsBody, user_id: int = Depends(require_user)):
    check_interval(body.interval)
    if body.language not in ('ru', 'en') or body.theme not in ('dark', 'light'):
        raise HTTPException(400, 'Недопустимые настройки')
    with db.Session.begin() as session:
        p = db.get_person(session, user_id)
        p.language, p.theme, p.interval, p.notifications = body.language, body.theme, body.interval, body.notifications
    return {'ok': True}


@app.get('/api/favorites')
async def favorites(user_id: int = Depends(require_user)):
    with db.Session() as session:
        items = session.scalars(select(db.Favorite.symbol).where(db.Favorite.user_id == user_id)).all()
    return {'symbols': items}


class FavoriteBody(BaseModel):
    symbol: str
    active: bool


@app.post('/api/favorites')
async def change_favorite(body: FavoriteBody, user_id: int = Depends(require_user)):
    sym = await check_symbol(body.symbol)
    with db.Session.begin() as session:
        existing = session.scalar(select(db.Favorite).where(db.Favorite.user_id == user_id, db.Favorite.symbol == sym))
        if body.active and not existing:
            session.add(db.Favorite(user_id=user_id, symbol=sym))
        if not body.active and existing:
            session.delete(existing)
    return {'ok': True}


@app.get('/api/history')
async def history(user_id: int = Depends(require_user)):
    with db.Session() as session:
        items = session.scalars(select(db.Signal).where(db.Signal.user_id == user_id).order_by(db.Signal.id.desc()).limit(100)).all()
        stats = {'TP1': 0, 'TP2': 0, 'TP3': 0, 'STOP': 0, 'ACTIVE': 0, 'WAIT': 0, 'AMBIGUOUS': 0, 'STALE': 0}
        for s in items:
            stats[s.status] = stats.get(s.status, 0) + 1
            if s.tp_reached >= 1: stats['TP1'] += 1
            if s.tp_reached >= 2: stats['TP2'] += 1
        return {'history': [db.signal_out(s) for s in items], 'stats': stats,
                'sampleSize': len(items), 'method': '1m candle high/low, same-candle TP/SL marked ambiguous'}


class AlertBody(BaseModel):
    symbol: str
    targetPrice: float = Field(gt=0)


@app.get('/api/alerts')
async def alerts(user_id: int = Depends(require_user)):
    with db.Session() as session:
        items = session.scalars(select(db.Alert).where(db.Alert.user_id == user_id).order_by(db.Alert.id.desc()).limit(100)).all()
        return {'alerts': [{'id': x.id, 'symbol': x.symbol, 'targetPrice': x.target_price, 'active': x.active} for x in items]}


@app.post('/api/alerts')
async def create_alert(body: AlertBody, user_id: int = Depends(require_user)):
    if not math.isfinite(body.targetPrice):
        raise HTTPException(400, 'Некорректная цена')
    sym = await check_symbol(body.symbol)
    ticks = await market.ticker(sym)
    if not ticks:
        raise HTTPException(503, 'Нет актуальной котировки')
    baseline = normalize_ticker(ticks[0])['lastPrice']
    if baseline <= 0:
        raise HTTPException(503, 'Нет актуальной котировки')
    with db.Session.begin() as session:
        count = len(session.scalars(select(db.Alert).where(db.Alert.user_id == user_id, db.Alert.active.is_(True))).all())
        if count >= 20:
            raise HTTPException(400, 'Максимум 20 активных уведомлений')
        db.get_person(session, user_id)
        session.add(db.Alert(user_id=user_id, symbol=sym, target_price=body.targetPrice, baseline_price=baseline))
    return {'ok': True}


@app.delete('/api/alerts/{alert_id}')
async def delete_alert(alert_id: int, user_id: int = Depends(require_user)):
    with db.Session.begin() as session:
        item = session.get(db.Alert, alert_id)
        if not item or item.user_id != user_id:
            raise HTTPException(404, 'Уведомление не найдено')
        session.delete(item)
    return {'ok': True}


class WatchBody(BaseModel):
    symbol: str
    interval: str = '15m'
    active: bool = True


@app.get('/api/watches')
async def watches(user_id: int = Depends(require_user)):
    with db.Session() as session:
        items = session.scalars(select(db.Watch).where(db.Watch.user_id == user_id)).all()
        return {'watches': [{'symbol': x.symbol, 'interval': x.interval, 'lastSide': x.last_side} for x in items]}


@app.post('/api/watches')
async def change_watches(body: WatchBody, user_id: int = Depends(require_user)):
    sym = await check_symbol(body.symbol)
    check_interval(body.interval)
    with db.Session.begin() as session:
        watches = session.scalars(select(db.Watch).where(db.Watch.user_id == user_id)).all()
        item = next((x for x in watches if x.symbol == sym and x.interval == body.interval), None)
        if body.active and not item:
            if len(watches) >= 5:
                raise HTTPException(400, 'Можно отслеживать до 5 пар')
            db.get_person(session, user_id)
            session.add(db.Watch(user_id=user_id, symbol=sym, interval=body.interval))
        if not body.active and item:
            session.delete(item)
    return {'ok': True}


@app.post('/telegram/webhook')
async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default='')):
    import hmac
    if not config.WEBHOOK_SECRET or not hmac.compare_digest(x_telegram_bot_api_secret_token, config.WEBHOOK_SECRET):
        raise HTTPException(403, 'Invalid Telegram webhook secret')
    update = await request.json()
    message = update.get('message') or {}
    chat = message.get('chat') or {}
    user = message.get('from') or {}
    if chat.get('type') == 'private' and int(user.get('id') or 0) > 0:
        uid, cid = int(user['id']), int(chat['id'])
        command = (message.get('text') or '').split(maxsplit=1)[0].split('@')[0].lower()
        if command == '/start':
            with db.Session.begin() as session:
                person = db.get_person(session, uid)
                person.chat_id = cid
            await telegram.welcome(cid)
        elif command in ('/pump_on', '/pump_off', '/signals_on', '/signals_off'):
            enabled = command.endswith('_on')
            is_pump = command.startswith('/pump_')
            model = db.PumpSubscription if is_pump else db.AutoSignalSubscription
            with db.Session.begin() as session:
                person = db.get_person(session, uid)
                person.chat_id = cid
                sub = session.get(model, uid)
                if sub:
                    sub.enabled = enabled
                else:
                    session.add(model(user_id=uid, enabled=enabled))
            kind = 'PUMP/DUMP' if is_pump else 'LONG/SHORT сценариев'
            await telegram.send(cid, f'🔔 Уведомления {kind}: {"включены" if enabled else "отключены"}.\n'
                                     'Переключить можно также во вкладке AI Сигналы.')
        elif command in ('/help', '/status'):
            with db.Session() as session:
                pump = session.get(db.PumpSubscription, uid)
                auto = session.get(db.AutoSignalSubscription, uid)
            await telegram.send(cid, f'📡 Настройки уведомлений\n'
                f'PUMP/DUMP: {"ВКЛ" if pump and pump.enabled else "ВЫКЛ"}\n'
                f'AI Сигналы: {"ВКЛ" if auto and auto.enabled else "ВЫКЛ"}\n\n'
                '/pump_on — включить резкие движения\n'
                '/pump_off — отключить резкие движения\n'
                '/signals_on — включить LONG/SHORT сценарии\n'
                '/signals_off — отключить LONG/SHORT сценарии\n'
                '/status — показать статус')
    return {'ok': True}


# One Railway service hosts both React build and FastAPI.
ROOT = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'


@app.get('/')
async def index():
    index_file = ROOT / 'index.html'
    if index_file.exists():
        return FileResponse(index_file)
    return {'message': 'Frontend not built. See README.md. API works on /api/health.'}


@app.get('/{path:path}')
async def serve_frontend(path: str):
    if path.startswith(('api/', 'telegram/')):
        raise HTTPException(404)
    target = (ROOT / path).resolve()
    if ROOT.exists() and target.is_relative_to(ROOT.resolve()) and target.is_file():
        return FileResponse(target)
    index_file = ROOT / 'index.html'
    if index_file.exists():
        return FileResponse(index_file)
    raise HTTPException(404)

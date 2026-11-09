"""Opt-in paper execution against public BingX candles; NEVER places exchange orders.

The ledger is intentionally simple: 1x synthetic LONG/SHORT positions, full margin
reserved in virtual USDT, capped allocation and stop risk, partial TP exits, modeled
fees/slippage. One worker / one Railway replica, as in the existing app.
"""
import datetime as dt
import math
import time
from sqlalchemy import select
from . import config, db
from .bingx import MarketDataError


def _utc_ms(value: dt.datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return int(value.timestamp() * 1000)


def entry_price(side: str, quote: float) -> float:
    return quote * (1 + config.PAPER_SLIPPAGE * (1 if side == 'LONG' else -1))


def exit_price(side: str, quote: float) -> float:
    return quote * (1 + config.PAPER_SLIPPAGE * (-1 if side == 'LONG' else 1))


def unrealized(pos: db.PaperPosition, current: float) -> float:
    direction = 1 if pos.side == 'LONG' else -1
    return (current - pos.entry_fill) * pos.remaining * direction


def open_for_signal(session, signal: db.AutoSignal, live_quote: float) -> list[tuple[int, int]]:
    """Create new opt-in positions only when a NEW global signal is published.

    Called in the SAME transaction as AutoSignal insertion. Never backfills past
    signals when a user switches the paper account on later.
    """
    if not math.isfinite(live_quote) or live_quote <= 0:
        return []
    if signal.side not in ('LONG', 'SHORT') or min(signal.entry, signal.stop, signal.tp1, signal.tp2, signal.tp3) <= 0:
        return []
    fill = entry_price(signal.side, live_quote)
    risk_per_unit = abs(fill - signal.stop)
    if risk_per_unit <= 0 or (signal.side == 'LONG' and fill <= signal.stop) or (signal.side == 'SHORT' and fill >= signal.stop):
        return []
    opened: list[tuple[int, int]] = []
    accounts = session.scalars(select(db.PaperAccount).where(db.PaperAccount.enabled.is_(True)).limit(200)).all()
    for account in accounts:
        def audit(code: str):
            session.add(db.PaperDecision(user_id=account.user_id,
                                         auto_signal_id=signal.id, reason=code))
        # Server-side limits regardless of frontend flags.
        existing = session.scalar(select(db.PaperPosition.id).where(
            db.PaperPosition.user_id == account.user_id,
            db.PaperPosition.auto_signal_id == signal.id,
        ))
        if existing:
            continue
        active = session.scalars(select(db.PaperPosition).where(
            db.PaperPosition.user_id == account.user_id, db.PaperPosition.status.in_(('OPEN', 'DATA_GAP'))
        )).all()
        if len(active) >= config.PAPER_MAX_POSITIONS or any(p.symbol == signal.symbol for p in active):
            audit('position_limit_or_same_symbol')
            continue
        budget = min(config.PAPER_RISK_FRACTION * account.initial_balance,
                     config.PAPER_RISK_FRACTION * max(0, account.cash))
        qty = min(budget / risk_per_unit,
                  (account.cash * config.PAPER_MAX_ALLOCATION) / (fill * (1 + config.PAPER_FEE_RATE)))
        if not math.isfinite(qty) or qty <= 0 or qty * fill < 5:
            audit('insufficient_virtual_budget')
            continue
        cost = qty * fill
        entry_fee = cost * config.PAPER_FEE_RATE
        if cost + entry_fee > account.cash + 1e-7:
            audit('insufficient_virtual_cash')
            continue
        account.cash -= cost + entry_fee
        position = db.PaperPosition(
            user_id=account.user_id, auto_signal_id=signal.id, symbol=signal.symbol,
            side=signal.side, entry_quote=live_quote, entry_fill=fill,
            stop=signal.stop, tp1=signal.tp1, tp2=signal.tp2, tp3=signal.tp3,
            quantity=qty, remaining=qty, margin_open=cost,
            fees=entry_fee, realized_pnl=-entry_fee, status='OPEN',
            # Do not use the candle that overlaps creation time: lookahead bias.
            last_checked=_utc_ms(db.now()) // 60000 * 60000,
        )
        session.add(position)
        session.flush()
        audit('opened')
        opened.append((account.user_id, position.id))
    return opened


def _close_piece(session, account: db.PaperAccount, position: db.PaperPosition,
                 qty: float, reference: float, reason: str, candle_ms: int):
    qty = min(max(0.0, qty), position.remaining)
    if qty <= 1e-12:
        return
    actual = exit_price(position.side, reference)
    gross = (actual - position.entry_fill) * qty * (1 if position.side == 'LONG' else -1)
    exit_fee = actual * qty * config.PAPER_FEE_RATE
    released = position.margin_open if qty >= position.remaining - 1e-10 else qty * position.entry_fill
    account.cash += released + gross - exit_fee
    position.remaining = max(0.0, position.remaining - qty)
    position.margin_open = max(0.0, position.margin_open - released)
    position.realized_pnl += gross - exit_fee
    position.fees += exit_fee
    session.add(db.PaperFill(position_id=position.id, reason=reason, quantity=qty,
                             reference_price=reference, fill_price=actual, fee=exit_fee,
                             pnl=gross-exit_fee, candle_time=candle_ms))


def _finish(position: db.PaperPosition, status: str, candle_ms: int):
    position.status = status
    position.finished_at = dt.datetime.fromtimestamp((candle_ms + 60000)/1000, dt.timezone.utc) if candle_ms else db.now()


def advance_candle(session, position: db.PaperPosition, candle: dict) -> str | None:
    """Process a fully CLOSED one-minute candle; conservative same-candle ambiguity."""
    if position.status != 'OPEN':
        return None
    candle_ms = int(candle['time'])
    if candle_ms <= position.last_checked:
        return None
    if position.last_checked and candle_ms > position.last_checked + 60000:
        position.status = 'DATA_GAP'  # Unknown path; don't manufacture a TP win.
        return 'DATA_GAP'
    lo, hi = float(candle['low']), float(candle['high'])
    if lo <= 0 or hi < lo:
        return None
    account = session.get(db.PaperAccount, position.user_id)
    if account is None:
        return None
    stop_hit = (lo <= position.stop) if position.side == 'LONG' else (hi >= position.stop)
    targets = (position.tp1, position.tp2, position.tp3)
    next_target = targets[position.tp_reached] if position.tp_reached < 3 else None
    next_hit = ((hi >= next_target) if position.side == 'LONG' else (lo <= next_target)) if next_target else False
    position.last_checked = candle_ms
    if stop_hit:
        _close_piece(session, account, position, position.remaining, position.stop,
                     'AMBIGUOUS_STOP' if next_hit else 'STOP', candle_ms)
        _finish(position, 'AMBIGUOUS' if next_hit else 'STOP', candle_ms)
        return position.status
    for i in range(position.tp_reached, 3):
        target = targets[i]
        hit = (hi >= target) if position.side == 'LONG' else (lo <= target)
        if not hit:
            break
        qty = position.remaining if i == 2 else min(position.quantity / 3, position.remaining)
        _close_piece(session, account, position, qty, target, f'TP{i+1}', candle_ms)
        position.tp_reached = i + 1
        if i == 2:
            _finish(position, 'TP3', candle_ms)
            return 'TP3'
    if _utc_ms(db.now()) - _utc_ms(position.created_at) > 24 * 3600_000:
        _close_piece(session, account, position, position.remaining, float(candle['close']), 'EXPIRED', candle_ms)
        _finish(position, 'EXPIRED', candle_ms)
        return 'EXPIRED'
    return None


def manual_close(session, position: db.PaperPosition, quote: float):
    """Close a paper position at a NEW public quote, even after a data gap."""
    if position.status not in ('OPEN', 'DATA_GAP'):
        raise ValueError('Эта позиция уже закрыта')
    if quote <= 0 or not math.isfinite(quote):
        raise ValueError('Нужна актуальная цена')
    account = session.get(db.PaperAccount, position.user_id)
    if account is None:
        raise ValueError('Демо-счёт не найден')
    _close_piece(session, account, position, position.remaining, quote, 'MANUAL', 0)
    position.status = 'MANUAL'
    position.finished_at = db.now()


async def update_positions(market):
    """Periodic minute-bar settlement; no private BingX endpoints."""
    with db.Session() as session:
        jobs = session.scalars(select(db.PaperPosition).where(db.PaperPosition.status == 'OPEN').limit(200)).all()
        symbols = sorted({p.symbol for p in jobs})
    now_ms = int(time.time() * 1000)
    events: list[tuple[int, str]] = []
    for symbol in symbols:
        try:
            candles = await market.candles(symbol, '1m', 300)
        except MarketDataError:
            continue
        closed = [c for c in candles if c['time'] + 60000 <= now_ms]
        if not closed:
            continue
        with db.Session.begin() as session:
            positions = session.scalars(select(db.PaperPosition).where(
                db.PaperPosition.symbol == symbol, db.PaperPosition.status == 'OPEN'
            )).all()
            for pos in positions:
                if closed[0]['time'] > pos.last_checked + 60000:
                    pos.status = 'DATA_GAP'
                    events.append((pos.user_id, f'⚠️ Демо {symbol}: пропуск минутных свечей. Позиция заморожена для ручного закрытия.'))
                    continue
                old_tp = pos.tp_reached
                for candle in closed:
                    if candle['time'] <= pos.last_checked:
                        continue
                    result = advance_candle(session, pos, candle)
                    if result:
                        break
                if pos.status not in ('OPEN',):
                    events.append((pos.user_id, f'📒 Демо {symbol} {pos.side}: {pos.status}, виртуальный результат {pos.realized_pnl:+.2f} USDT (с комиссиями).'))
                elif pos.tp_reached > old_tp:
                    events.append((pos.user_id, f'🎯 Демо {symbol}: достигнут TP{pos.tp_reached}. Оставшаяся часть позиции отслеживается.'))
    return events


def position_out(position: db.PaperPosition, fills: list[db.PaperFill], price: float | None):
    fresh = price is not None and price > 0
    return {
        'id': position.id, 'signalId': position.auto_signal_id, 'symbol': position.symbol,
        'side': position.side, 'status': position.status, 'entryQuote': position.entry_quote,
        'entryFill': position.entry_fill, 'stop': position.stop,
        'takeProfits': [position.tp1, position.tp2, position.tp3],
        'quantity': position.quantity, 'remaining': position.remaining,
        'marginOpen': position.margin_open, 'realizedPnl': round(position.realized_pnl, 6),
        'unrealizedPnl': round(unrealized(position, price), 6) if fresh and position.status in ('OPEN','DATA_GAP') else None,
        'fees': round(position.fees, 6), 'tpReached': position.tp_reached,
        'lastPrice': price, 'lastChecked': position.last_checked,
        'createdAt': position.created_at.isoformat(),
        'finishedAt': position.finished_at.isoformat() if position.finished_at else None,
        'fills': [{'reason': f.reason, 'quantity': f.quantity,
                   'referencePrice': f.reference_price, 'fillPrice': f.fill_price,
                   'fee': f.fee, 'pnl': f.pnl} for f in fills],
    }


def account_snapshot(session, user_id: int, prices: dict[str, float] | None):
    account = session.get(db.PaperAccount, user_id)
    if not account:
        return {'enabled': False, 'exists': False, 'initialBalance': config.PAPER_START_USDT,
                'cash': config.PAPER_START_USDT, 'equity': config.PAPER_START_USDT,
                'positions': [], 'latestDecisions': [], 'stats': {'closed': 0, 'win': 0, 'loss': 0, 'netPnl': 0.0}}
    positions = session.scalars(select(db.PaperPosition).where(db.PaperPosition.user_id == user_id)
                                .order_by(db.PaperPosition.id.desc())).all()
    decisions = session.scalars(select(db.PaperDecision).where(db.PaperDecision.user_id == user_id)
                                .order_by(db.PaperDecision.id.desc()).limit(6)).all()
    latest_decisions = [{'signalId': d.auto_signal_id, 'reason': d.reason,
                         'createdAt': d.created_at.isoformat()} for d in decisions]
    recent = positions[:150]
    fill_ids = [p.id for p in recent]
    fills = session.scalars(select(db.PaperFill).where(db.PaperFill.position_id.in_(fill_ids))
                            .order_by(db.PaperFill.id.asc())).all() if fill_ids else []
    by_position: dict[int, list[db.PaperFill]] = {}
    for f in fills:
        by_position.setdefault(f.position_id, []).append(f)
    open_positions = [p for p in positions if p.status in ('OPEN', 'DATA_GAP')]
    # Without a fresh ticker for EVERY open position, unknown mark-to-market is null.
    fully_priced = prices is not None and all(prices.get(p.symbol, 0) > 0 for p in open_positions)
    equity = None
    if fully_priced:
        equity = account.cash + sum(p.margin_open + unrealized(p, prices[p.symbol]) for p in open_positions)
    closed = [p for p in positions if p.status not in ('OPEN', 'DATA_GAP')]
    return {'exists': True, 'enabled': account.enabled, 'initialBalance': account.initial_balance,
            'cash': round(account.cash, 6), 'equity': round(equity, 6) if equity is not None else None,
            'pricesFresh': fully_priced,
            'positions': [position_out(p, by_position.get(p.id, []), prices.get(p.symbol) if prices else None) for p in recent],
            'latestDecisions': latest_decisions,
            'stats': {'closed': len(closed), 'win': sum(p.realized_pnl > 0 for p in closed),
                      'loss': sum(p.realized_pnl < 0 for p in closed),
                      'netPnl': round(sum(p.realized_pnl for p in positions), 6),
                      'active': len(open_positions)},
            'method': 'virtual 1x; adverse slippage 0.05% per fill; fees 0.05% per side; '
                      'three 1/3 profit exits; stop first when TP and SL share a candle; '
                      'funding not included; no real exchange orders'}

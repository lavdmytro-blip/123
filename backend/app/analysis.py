"""Deterministic, auditable technical-analysis scenarios. Not investment advice.

Works only on *completed* candles. Never invents price levels or success odds.
"""
import math
import time
import pandas as pd
from .config import INTERVALS


def _num(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def analyze(symbol: str, interval: str, candles: list[dict], extras: dict | None = None, now_ms: int | None = None) -> dict:
    now = now_ms or int(time.time() * 1000)
    step_ms = INTERVALS[interval] * 1000
    # The current unfinished candle is intentionally ignored.
    rows = [c for c in candles if c['time'] + step_ms <= now and c['close'] > 0]
    rows = sorted(rows, key=lambda c: c['time'])
    result = {
        'symbol': symbol, 'interval': interval, 'generatedAt': now,
        'side': 'WAIT', 'entry': None, 'stopLoss': None, 'takeProfits': [],
        'riskReward': None, 'strength': 0, 'reasons': [], 'risks': [],
        'metrics': {}, 'source': 'BingX public market data', 'price': None,
        'summary': '', 'levels': {}, 'method': 'rules-v1',
    }
    if len(rows) < 210:
        result['summary'] = 'Недостаточно завершённых свечей для достоверного анализа.'
        return result
    latest_ms = rows[-1]['time'] + step_ms
    if now - latest_ms > step_ms * 2.5:
        result['summary'] = 'Свечи устарели. Анализ временно недоступен.'
        return result
    df = pd.DataFrame(rows)
    for c in ('open', 'high', 'low', 'close', 'volume'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
    if len(df) < 210:
        result['summary'] = 'Недостаточно корректных рыночных данных.'
        return result
    close, high, low, volume = df['close'], df['high'], df['low'], df['volume']
    last = float(close.iloc[-1])
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    avg_down = down.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi = 100 - 100 / (1 + avg_up / avg_down.replace(0, float('nan')))
    rsi = rsi.fillna(100 if float(avg_up.iloc[-1]) > 0 else 50)
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    rolling_mean = close.rolling(20).mean()
    rolling_std = close.rolling(20).std(ddof=0)
    bb_upper, bb_lower = rolling_mean + 2 * rolling_std, rolling_mean - 2 * rolling_std
    prev_close = close.shift(1)
    tr = pd.concat([(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    atr_last = float(atr.iloc[-1]); rsi_last = float(rsi.iloc[-1]); hist_last = float(histogram.iloc[-1])
    vol_avg = float(volume.iloc[-21:-1].mean()); vol_ratio = float(volume.iloc[-1] / vol_avg) if vol_avg > 0 else 0
    # Exclude the current candle from prior support/resistance candidates.
    recent = df.iloc[-100:-1]
    piv_hi, piv_lo = [], []
    for i in range(2, len(recent) - 2):
        hs = recent['high'].iloc[i-2:i+3]
        ls = recent['low'].iloc[i-2:i+3]
        if float(recent['high'].iloc[i]) == float(hs.max()):
            piv_hi.append(float(recent['high'].iloc[i]))
        if float(recent['low'].iloc[i]) == float(ls.min()):
            piv_lo.append(float(recent['low'].iloc[i]))
    support_candidates = [x for x in piv_lo if x < last]
    resist_candidates = [x for x in piv_hi if x > last]
    support = max(support_candidates) if support_candidates else float(recent['low'].min())
    resistance = min(resist_candidates) if resist_candidates else float(recent['high'].max())

    pos = neg = 0
    reasons = []
    risks = []
    def vote(direction, weight, label):
        nonlocal pos, neg
        if direction == 'LONG':
            pos += weight
        elif direction == 'SHORT':
            neg += weight
        reasons.append({'direction': direction, 'text': label, 'weight': weight})

    fast = float(ema20.iloc[-1]); medium = float(ema50.iloc[-1]); slow = float(ema200.iloc[-1])
    if last > fast > medium > slow:
        vote('LONG', 3, 'Цена и EMA 20/50/200 расположены в восходящем порядке.')
    elif last < fast < medium < slow:
        vote('SHORT', 3, 'Цена и EMA 20/50/200 расположены в нисходящем порядке.')
    else:
        vote('WAIT', 0, 'EMA не подтверждают однозначный тренд.')
    if 52 <= rsi_last <= 68:
        vote('LONG', 1, f'RSI {rsi_last:.1f}: умеренный положительный импульс.')
    elif 32 <= rsi_last <= 48:
        vote('SHORT', 1, f'RSI {rsi_last:.1f}: умеренный отрицательный импульс.')
    else:
        risks.append(f'RSI {rsi_last:.1f}: крайние или нейтральные значения затрудняют оценку.')
    previous_hist = float(histogram.iloc[-2])
    if hist_last > 0 and hist_last > previous_hist:
        vote('LONG', 2, 'Гистограмма MACD положительна и растёт.')
    elif hist_last < 0 and hist_last < previous_hist:
        vote('SHORT', 2, 'Гистограмма MACD отрицательна и снижается.')
    else:
        risks.append('MACD не подтверждает усиление импульса.')
    if vol_ratio >= 1.2:
        direction = 'LONG' if float(close.iloc[-1] - close.iloc[-2]) > 0 else 'SHORT'
        vote(direction, 1, f'Объём последней свечи в {vol_ratio:.2f} раза выше среднего за 20 свечей.')
    else:
        risks.append('Объём не даёт сильного дополнительного подтверждения.')
    last6 = close.iloc[-6:].to_numpy()
    if last6[-1] > last6[0] and float(high.iloc[-5:].max()) > float(high.iloc[-10:-5].max()):
        vote('LONG', 1, 'Недавнее движение обновляет локальные максимумы.')
    elif last6[-1] < last6[0] and float(low.iloc[-5:].min()) < float(low.iloc[-10:-5].min()):
        vote('SHORT', 1, 'Недавнее движение обновляет локальные минимумы.')
    else:
        risks.append('Структура локального движения неоднозначна.')
    if last > float(bb_upper.iloc[-1]) or last < float(bb_lower.iloc[-1]):
        risks.append('Цена за границей полос Боллинджера: возможен возврат к средней.')

    metrics = {
        'ema20': fast, 'ema50': medium, 'ema200': slow, 'rsi': rsi_last,
        'macd': float(macd_line.iloc[-1]), 'macdSignal': float(signal.iloc[-1]),
        'macdHistogram': hist_last, 'atr': atr_last, 'volumeRatio': vol_ratio,
        'bbUpper': float(bb_upper.iloc[-1]), 'bbLower': float(bb_lower.iloc[-1]),
        'bullScore': pos, 'bearScore': neg,
    }
    extra = extras or {}
    funding = extra.get('funding') if isinstance(extra.get('funding'), dict) else {}
    oi = extra.get('openInterest') if isinstance(extra.get('openInterest'), dict) else {}
    depth = extra.get('depth') if isinstance(extra.get('depth'), dict) else {}
    metrics['fundingRate'] = _num((funding or {}).get('fundingRate'))
    metrics['openInterest'] = _num((oi or {}).get('openInterest'))
    try:
        bid_sum = sum(float(q) for _, q in depth.get('bids', []))
        ask_sum = sum(float(q) for _, q in depth.get('asks', []))
        metrics['bidAskRatio'] = bid_sum / ask_sum if ask_sum else None
    except (TypeError, ValueError):
        metrics['bidAskRatio'] = None
    if metrics['fundingRate'] is not None and abs(metrics['fundingRate']) > 0.0005:
        risks.append('Повышенная ставка финансирования: риск резкого движения или перегрева позиций.')
    if metrics['openInterest'] is None:
        risks.append('Открытый интерес недоступен; эта оценка пропущена.')
    if metrics['bidAskRatio'] is None:
        risks.append('Стакан недоступен; оценка дисбаланса не учитывалась.')
    elif metrics['bidAskRatio'] > 1.3:
        reasons.append({'direction': 'LONG', 'text': 'Покупки преобладают в текущем срезе стакана, но заявки могут исчезать.', 'weight': 0})
    elif metrics['bidAskRatio'] < 0.77:
        reasons.append({'direction': 'SHORT', 'text': 'Продажи преобладают в текущем срезе стакана, но заявки могут исчезать.', 'weight': 0})

    result.update(price=last, reasons=reasons, risks=risks, metrics=metrics,
                  levels={'support': support, 'resistance': resistance},
                  strength=max(pos, neg))
    side = 'LONG' if pos >= 6 and pos - neg >= 4 else ('SHORT' if neg >= 6 and neg - pos >= 4 else 'WAIT')
    if not math.isfinite(atr_last) or atr_last <= 0 or atr_last / last > 0.15:
        side = 'WAIT'
        risks.append('Волатильность нельзя надёжно оценить.')
    if side == 'WAIT':
        result['summary'] = 'Недостаточно согласованных подтверждений. Лучше дождаться новой структуры цены.'
        return result
    # Stop level derives from nearest structure and ATR; cap excessively distant stops.
    if side == 'LONG':
        structural_stop = support - 0.2 * atr_last if support < last else last - 1.5 * atr_last
        stop = min(last - 1.5 * atr_last, structural_stop)
        risk = last - stop
        if resistance > last and resistance - last < 1.3 * risk:
            risks.append('Ближайшее сопротивление слишком близко к точке входа.')
            side = 'WAIT'
        tps = [last + risk * x for x in (1.5, 2, 3)]
    else:
        structural_stop = resistance + 0.2 * atr_last if resistance > last else last + 1.5 * atr_last
        stop = max(last + 1.5 * atr_last, structural_stop)
        risk = stop - last
        if support < last and last - support < 1.3 * risk:
            risks.append('Ближайшая поддержка слишком близко к точке входа.')
            side = 'WAIT'
        tps = [last - risk * x for x in (1.5, 2, 3)]
    if risk > 4 * atr_last or risk / last > 0.1 or min(tps) <= 0:
        side = 'WAIT'
        risks.append('Стоп слишком далеко или одна из целей некорректна.')
    if side == 'WAIT':
        result['summary'] = 'Есть признаки движения, но ближайшие уровни не дают обоснованного сценария.'
        return result
    result.update(side=side, entry=last, stopLoss=stop, takeProfits=tps, riskReward=1.5,
                  summary=('Сценарий роста' if side == 'LONG' else 'Сценарий снижения') +
                  ' подтверждён несколькими техническими факторами. Результат не гарантирован.')
    return result

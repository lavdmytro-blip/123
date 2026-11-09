import math
import time
from app.analysis import analyze
from app.worker import crossed, _status_at_candle


def sample_candles(step=900_000, n=310, direction=1):
    last_closed = (int(time.time()*1000)//step)*step-step
    start = last_closed - (n-1)*step
    rows = []
    for i in range(n):
        p = 100 + i*0.08*direction + math.sin(i/3)*0.22
        rows.append({'time': start+i*step, 'open': p-0.03, 'high': p+0.19,
                     'low': p-0.2, 'close': p, 'volume': 150+(i%7)*5, 'closeTime': start+(i+1)*step-1})
    return rows


def test_analysis_is_consistent_for_history():
    rows = sample_candles()
    result = analyze('BTC-USDT','15m',rows,{},int(time.time()*1000))
    assert result['side'] in ('LONG','SHORT','WAIT')
    assert result['price'] == rows[-1]['close']
    assert result['metrics']['rsi'] >= 0
    assert 0 <= result['metrics']['rsi'] <= 100
    if result['side'] == 'LONG':
        assert result['stopLoss'] < result['entry'] < result['takeProfits'][0]
    if result['side'] == 'SHORT':
        assert result['takeProfits'][0] < result['entry'] < result['stopLoss']
    if result['side'] == 'WAIT':
        assert result['stopLoss'] is None
        assert not result['takeProfits']


def test_unfinished_candle_is_not_used():
    step=900_000
    now=int(time.time()*1000)
    rows=sample_candles()
    old=analyze('BTC-USDT','15m',rows,{},now)
    current_start=now//step*step
    rows.append({'time':current_start,'open':100,'high':1000000,'low':1,'close':900000,'volume':10000})
    new=analyze('BTC-USDT','15m',rows,{},now)
    assert old['price']==new['price']
    assert old['metrics']==new['metrics']


def test_stale_and_missing_data_do_not_create_levels():
    assert analyze('BTC-USDT','15m',sample_candles(n=20))['side']=='WAIT'
    rows=sample_candles()
    for c in rows:c['time']-=86400000
    stale=analyze('BTC-USDT','15m',rows)
    assert stale['side']=='WAIT' and stale['entry'] is None


def test_crossing_alerts():
    assert crossed(100,102,101)
    assert crossed(102,100,101)
    assert not crossed(100,100.1,101)


def test_same_minute_tp_and_sl_is_ambiguous():
    class S:
        side='LONG';stop=99;tp1=101;tp2=102;tp3=103;tp_reached=0
    assert _status_at_candle(S(), {'low':98,'high':102})==('AMBIGUOUS',0)
    assert _status_at_candle(S(), {'low':100,'high':103})==('TP3',3)
    assert _status_at_candle(S(), {'low':98,'high':100})[0]=='STOP'

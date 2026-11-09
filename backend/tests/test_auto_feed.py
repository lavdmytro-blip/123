"""Offline tests: no real BingX calls and no real Telegram notifications."""
import asyncio
import json
import types
import datetime as dt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import db, worker, main, config


def isolated_db(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    session = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, 'Session', session)
    return session


class FakeMarket:
    def __init__(self, rows): self.rows = rows
    async def symbols(self): return ['BTC-USDT']
    async def candles(self, symbol, interval, limit=310): return self.rows
    async def ticker(self, symbol=None):
        return [{'symbol': 'BTC-USDT', 'lastPrice': '100', 'priceChangePercent': '0'}]


def test_scanner_deduplicates_closed_candle_and_public_api(monkeypatch):
    session_factory = isolated_db(monkeypatch)
    step = 900_000
    now = (int(dt.datetime.now(dt.timezone.utc).timestamp() * 1000) // step) * step + 60_000
    monkeypatch.setattr(worker, 'time', types.SimpleNamespace(time=lambda: now/1000))
    monkeypatch.setattr(config, 'AUTO_SIGNALS_ENABLED', True)
    monkeypatch.setattr(config, 'AUTO_SIGNALS_SYMBOLS', ['BTC-USDT'])
    monkeypatch.setattr(config, 'AUTO_SIGNALS_INTERVAL', '15m')
    rows = [{'time':now - (i+1)*step, 'open':100, 'close':100, 'high':101,
             'low':99, 'volume':10} for i in range(310)]
    rows.sort(key=lambda x:x['time'])
    result = {'symbol':'BTC-USDT','interval':'15m','generatedAt':now,
              'side':'LONG','price':100,'entry':100.0,'stopLoss':98.0,
              'takeProfits':[103.,105.,107.], 'metrics':{'atr':1.},
              'summary':'Виртуальный сценарий','reasons':[],'risks':[],'strength':7}
    monkeypatch.setattr(worker, 'analyze', lambda *args, **kwargs: result)
    market = FakeMarket(rows)
    asyncio.run(worker.auto_scan(market))
    asyncio.run(worker.auto_scan(market))
    with session_factory() as session:
        items = session.scalars(select(db.AutoSignal)).all()
        assert len(items) == 1
        assert items[0].status == 'ACTIVE'
        assert items[0].entry == 100
    monkeypatch.setattr(main, 'market', market)
    feed = asyncio.run(main.auto_signals(user_id=None))
    assert len(feed['signals']) == 1
    assert feed['signals'][0]['symbol'] == 'BTC-USDT'
    assert feed['signals'][0]['takeProfits'] == [103.,105.,107.]
    assert feed['subscribed'] is False
    assert feed['prices']['BTC-USDT'] == 100


def test_telegram_subscription_is_explicit_opt_in(monkeypatch):
    session_factory = isolated_db(monkeypatch)
    async def run():
        before = await main.auto_subscription(main.AutoSubscriptionBody(enabled=True), user_id=2323)
        after = await main.auto_subscription(main.AutoSubscriptionBody(enabled=False), user_id=2323)
        return before, after
    enabled, disabled = asyncio.run(run())
    assert enabled == {'enabled': True}
    assert disabled == {'enabled': False}
    with session_factory() as session:
        sub = session.get(db.AutoSignalSubscription, 2323)
        assert sub.enabled is False


def test_auto_status_with_both_targets_same_minute():
    sig = db.AutoSignal(symbol='BTC-USDT', interval='15m', side='SHORT',entry=100,
        stop=102,tp1=98,tp2=97,tp3=95, result_json=json.dumps({}),candle_time=10, tp_reached=0)
    assert worker._status_at_candle(sig,{'low':97,'high':103}) == ('AMBIGUOUS',0)
    assert worker._status_at_candle(sig,{'low':96,'high':101}) == (None,2)

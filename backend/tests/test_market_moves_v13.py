"""Read-only rapid-move detector tests: no external requests or Telegram sends."""
import asyncio
import datetime as dt
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import config, db, main, market_moves


def isolated_db(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False},poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, 'Session', factory)
    return factory


def test_window_requires_real_five_minute_history():
    fn = market_moves.baseline_and_change
    assert fn([], 1000, 110) is None
    assert fn([(700,100)],999,110) is None
    assert round(fn([(699,100)],1000,110)[1], 6) == 10
    assert fn([(639,100)],1000,110) is None  # stale snapshot
    assert fn([(700,0)],1000,110) is None


def minutes(now_ms, last=100, prev=10):
    current_minute = now_ms // 60000 * 60000
    result = []
    for i in range(30):
        minute = current_minute - (30-i)*60000
        vol = last if i >= 25 else prev
        result.append(dict(time=minute,open=1,high=1.05,low=.95,close=1,volume=vol))
    return result


def test_volumes_require_fresh_contiguous_closed_candles():
    now = 1_800_000_000_000
    bars = minutes(now)
    ratio, volume = market_moves.volume_confirmation(bars, now, 200, 2)
    assert ratio == 10.0 and volume == 500
    assert market_moves.volume_confirmation(bars, now, 600, 2) is None
    assert market_moves.volume_confirmation(bars, now, 200, 11) is None
    assert market_moves.volume_confirmation(bars[:-1], now+300_000, 200, 2) is None
    broken = bars[:]
    broken[22] = dict(broken[22], time=broken[22]['time'] + 20_000)
    assert market_moves.volume_confirmation(broken, now, 200, 2) is None


def test_market_event_persists_and_deduplicates(monkeypatch):
    factory = isolated_db(monkeypatch)
    monkeypatch.setattr(config, 'PUMP_MIN_24H_USDT', 10_000)
    monkeypatch.setattr(config, 'MARKET_MIN_24H_USDT', 10_000)
    monkeypatch.setattr(config, 'PUMP_MIN_TURNOVER_USDT', 200)
    monkeypatch.setattr(config, 'PUMP_VOLUME_MULTIPLIER', 2.0)
    monkeypatch.setattr(config, 'PUMP_THRESHOLD_PERCENT', 3.0)
    class FakeMarket:
        price = 100
        candle_queries = 0
        async def contracts(self):
            return [{'symbol':'BTC-USDT','launchTime':1_700_000_000_000}]
        async def ticker(self):
            return [{'symbol':'BTC-USDT','lastPrice':str(self.price),'quoteVolume':'200000'}]
        async def candles(self,symbol,interval,limit=35):
            self.candle_queries += 1
            return minutes(1_800_000_000_000)
    market = FakeMarket()
    monkeypatch.setattr(main, 'market', market)
    watcher = market_moves.MoveMonitor()
    sent=[]
    async def sender(*args): sent.append(args)
    monkeypatch.setattr(watcher, '_notify', sender)
    at = 1_800_000_000.0
    async def scenario():
        await watcher.run_once(market, at-305)  # baseline 100
        market.price = 104
        await watcher.run_once(market, at)
        await watcher.run_once(market, at+20)
    asyncio.run(scenario())
    with factory() as session:
        events = session.scalars(select(db.PumpEvent)).all()
        assert len(events)==1
        assert events[0].direction=='PUMP'
        assert events[0].change_pct==4.0
        assert events[0].volume_ratio==10
    assert len(sent)==1
    assert market.candle_queries==1
    result=asyncio.run(main.pump_events(user_id=None))
    assert len(result['events'])==1
    assert result['subscribed'] is False


def test_telegram_pump_subscription_is_opt_in(monkeypatch):
    factory=isolated_db(monkeypatch)
    with factory.begin() as session:
        p = db.get_person(session, 555)
        p.chat_id = 555
    async def scenario():
        assert (await main.pump_subscription(main.PumpSubscriptionBody(enabled=True),user_id=555))['enabled']
        assert not (await main.pump_subscription(main.PumpSubscriptionBody(enabled=False),user_id=555))['enabled']
    asyncio.run(scenario())
    with factory() as session:
        assert session.get(db.PumpSubscription,555).enabled is False


def test_private_chat_commands_allow_opt_in_without_mini_app(monkeypatch):
    factory = isolated_db(monkeypatch)
    monkeypatch.setattr(config, 'WEBHOOK_SECRET', 'testsecret-testsecret-testsecret-32')
    monkeypatch.setattr(config, 'BOT_TOKEN', 'test-token')
    messages = []
    async def fake_send(chat, text): messages.append((chat,text))
    from app import telegram
    monkeypatch.setattr(telegram, 'send', fake_send)
    class Request:
        def __init__(self, command, kind='private'): self.command,self.kind=command,kind
        async def json(self):
            return {'message': {'text': self.command, 'from': {'id': 456},
                                'chat': {'id': 456 if self.kind=='private' else -456,'type':self.kind}}}
    async def scenario():
        await main.webhook(Request('/pump_on'),config.WEBHOOK_SECRET)
        await main.webhook(Request('/signals_on'),config.WEBHOOK_SECRET)
        await main.webhook(Request('/pump_off', 'supergroup'),config.WEBHOOK_SECRET)
        await main.webhook(Request('/status'),config.WEBHOOK_SECRET)
    asyncio.run(scenario())
    with factory() as session:
        assert session.get(db.PumpSubscription,456).enabled is True
        assert session.get(db.AutoSignalSubscription,456).enabled is True
        assert session.get(db.Person,456).chat_id == 456
    assert len(messages)==3
    assert 'PUMP/DUMP: ВКЛ' in messages[-1][1]

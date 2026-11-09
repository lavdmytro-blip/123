"""Tests for the specified balanced automatic-signal universe. No live requests."""
import asyncio
import time
from app import config, market_filter, market_moves, worker, db
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = 1_800_000_000_000
OLD = NOW - 60 * 86_400_000
RECENT = NOW - 10 * 86_400_000

def c(sym, start=OLD, **kwargs):
    return {'symbol': sym, 'launchTime': start, **kwargs}

def t(sym, volume=20_000_000, price=1):
    return {'symbol': sym, 'quoteVolume': str(volume), 'lastPrice': str(price)}


def test_balanced_uses_age_volume_and_nonstandard_exclusions(monkeypatch):
    monkeypatch.setattr(config,'MARKET_FILTER_MODE','balanced')
    monkeypatch.setattr(config,'MARKET_MIN_24H_USDT',10_000_000)
    monkeypatch.setattr(config,'MARKET_MIN_LISTING_DAYS',30)
    monkeypatch.setattr(config,'MARKET_EXCLUDE_NONSTANDARD',True)
    contracts=[c('BTC-USDT'),c('ETH-USDT', RECENT),c('SOL-USDT'),
               c('NCSKABNB2-USDT'),c('BTC3L-USDT'),c('1000PEPE-USDT'),
               c('XRP-USDT', None),c('DOGE-USDT', 0),c('ADA-USDT')]
    ticks=[t('BTC-USDT', 10_000_000),t('ETH-USDT'),t('SOL-USDT',9_999_999),
           t('NCSKABNB2-USDT'),t('BTC3L-USDT'),t('1000PEPE-USDT'),
           t('XRP-USDT'),t('DOGE-USDT'),t('ADA-USDT')]
    allowed, report=market_filter.eligible_markets(contracts,ticks,NOW)
    assert allowed == {'BTC-USDT','ADA-USDT'}
    assert report['eligible']==2 and report['evaluated']==9
    assert report['reasons']['too_new']==1
    assert report['reasons']['nonstandard']==3
    assert report['reasons']['low_or_unknown_volume']==1
    assert report['reasons']['unknown_listing_date']==2


def test_missing_contract_info_and_quote_volume_are_never_accepted(monkeypatch):
    monkeypatch.setattr(config,'MARKET_MIN_24H_USDT',10_000_000)
    assert market_filter.eligible_markets([], [t('BTC-USDT')], NOW)[0]==set()
    assert market_filter.eligible_markets([c('BTC-USDT')], [{'symbol':'BTC-USDT','lastPrice':'1'}], NOW)[0]==set()


def test_scanner_passes_only_balanced_pairs_to_candle_analysis(monkeypatch):
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db,'Session', sessionmaker(engine))
    monkeypatch.setattr(config,'MARKET_MIN_24H_USDT',10_000_000)
    monkeypatch.setattr(config,'AUTO_SIGNALS_UNIVERSE','ALL')
    monkeypatch.setattr(config,'AUTO_SIGNALS_ENABLED',True)
    monkeypatch.setattr(config,'AUTO_SCAN_PACE_SECONDS',0)
    actual_now=int(time.time()*1000)
    class Fake:
        def __init__(self): self.visited=[]
        async def contracts(self):
            return [c('BTC-USDT',actual_now-60*86_400_000),
                    c('SOL-USDT',actual_now-60*86_400_000),
                    c('NCSKABNB2-USDT',actual_now-60*86_400_000),
                    c('NEW-USDT',actual_now-10*86_400_000)]
        async def ticker(self):
            return [t('BTC-USDT'),t('SOL-USDT',1_000_000),t('NCSKABNB2-USDT'),t('NEW-USDT')]
        async def candles(self, symbol, interval, limit=310):
            self.visited.append(symbol)
            return []
    fake=Fake()
    count=asyncio.run(worker.auto_scan(fake))
    assert count == 1
    assert fake.visited==['BTC-USDT']


def test_pump_monitor_ignores_not_eligible_symbols(monkeypatch):
    monkeypatch.setattr(config,'MARKET_MIN_24H_USDT',10_000_000)
    monkeypatch.setattr(config,'PUMP_THRESHOLD_PERCENT',3.0)
    class Fake:
        def __init__(self): self.price=1; self.candles_called=[]
        async def contracts(self):
            return [c('BTC-USDT'),c('NCSKABNB2-USDT'),c('LOW-USDT')]
        async def ticker(self):
            return [t('BTC-USDT',20_000_000,self.price),t('NCSKABNB2-USDT',30_000_000,self.price),t('LOW-USDT',100_000,self.price)]
        async def candles(self, sym, interval, limit=35):
            self.candles_called.append(sym)
            return []
    fake=Fake()
    monitor=market_moves.MoveMonitor()
    async def go():
        await monitor.run_once(fake, NOW/1000-305)
        fake.price=1.05
        await monitor.run_once(fake, NOW/1000)
    asyncio.run(go())
    assert monitor.observed==1
    assert monitor.eligible_symbols=={'BTC-USDT'}
    assert set(monitor.history)=={'BTC-USDT'}
    assert fake.candles_called==['BTC-USDT']


def test_jup_is_not_confused_with_leveraged_up_token(monkeypatch):
    monkeypatch.setattr(config,'MARKET_MIN_24H_USDT',10_000_000)
    eligible, _ = market_filter.eligible_markets([c('JUP-USDT')],[t('JUP-USDT')],NOW)
    assert eligible == {'JUP-USDT'}
    eligible, _ = market_filter.eligible_markets([c('BTCUP-USDT')],[t('BTCUP-USDT')],NOW)
    assert not eligible

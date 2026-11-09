"""Offline checks for all-market rotation, logo validation and scan state."""
import asyncio
import types
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import worker, config, db, logos


def test_universe_all_rotates_all_pairs_even_with_legacy_five(monkeypatch):
    monkeypatch.setattr(config, 'AUTO_SIGNALS_UNIVERSE', 'ALL')
    monkeypatch.setattr(config, 'AUTO_SIGNALS_SYMBOLS', ['BTC-USDT', 'ETH-USDT'])
    markets = ['ALT'+str(i)+'-USDT' for i in range(55)]+['BTC-USDT', 'ETH-USDT']
    tickers = [{'symbol': s, 'volume24h': i*100} for i,s in enumerate(markets)]
    ordered = worker.ordered_universe(markets, tickers)
    assert len(ordered) == len(set(markets)) == 57
    assert ordered[:2] == ['BTC-USDT', 'ETH-USDT']
    assert set(ordered) == set(markets)


def test_custom_scope_only_when_explicit(monkeypatch):
    monkeypatch.setattr(config, 'AUTO_SIGNALS_UNIVERSE', 'CUSTOM')
    monkeypatch.setattr(config, 'AUTO_SIGNALS_SYMBOLS', ['ETH-USDT'])
    assert worker.ordered_universe(['BTC-USDT', 'ETH-USDT'],[]) == ['ETH-USDT']


def test_scanner_progress_persists(monkeypatch):
    engine=create_engine('sqlite://',poolclass=StaticPool, connect_args={'check_same_thread':False})
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db,'Session',sessionmaker(engine))
    worker._set_scan_progress(total=500,scanned=12,last_symbol='BTC-USDT')
    worker._set_scan_progress(scanned=500,last_symbol='ZK-USDT',completed=True)
    with db.Session() as session:
        s=session.get(db.ScannerState,1)
        assert s.total == 500 and s.scanned == 500 and s.round == 1
        assert s.last_completed_at is not None


def test_logos_prioritize_first_market_cap_and_reject_unknown_url():
    m=logos.images_from_markets([[{'symbol':'btc','image':'https://coin-images.coingecko.com/a.png'},
                                  {'symbol':'BTC','image':'https://evil.example/picture.png'}],
                                 [{'symbol':'btc','image':'https://coin-images.coingecko.com/other.png'},
                                  {'symbol':'pepe','image':'https://coin-images.coingecko.com/p.png'}]])
    assert m['BTC']=='https://coin-images.coingecko.com/a.png'
    assert m['PEPE']=='https://coin-images.coingecko.com/p.png'
    assert not logos._safe_image('http://coin-images.coingecko.com/a.png')


def test_all_market_scan_visits_more_than_old_eight_symbol_cap(monkeypatch):
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db,'Session',sessionmaker(engine))
    monkeypatch.setattr(config,'AUTO_SIGNALS_ENABLED',True)
    monkeypatch.setattr(config,'AUTO_SIGNALS_UNIVERSE','ALL')
    monkeypatch.setattr(config,'AUTO_SIGNALS_INTERVAL','15m')
    monkeypatch.setattr(config,'AUTO_SCAN_PACE_SECONDS',0)
    names=['COIN'+str(i)+'-USDT' for i in range(26)]
    class ManyMarkets:
        def __init__(self): self.visited=[]
        async def symbols(self): return names
        async def ticker(self): return [dict(symbol=x,lastPrice='1',quoteVolume='100') for x in names]
        async def candles(self,symbol,interval,limit=310):
            self.visited.append(symbol)
            return []  # no data -> no fabricated signal
    fake=ManyMarkets()
    processed=asyncio.run(worker.auto_scan(fake))
    assert processed == len(names)
    assert set(fake.visited)==set(names)
    with db.Session() as session:
        state=session.get(db.ScannerState,1)
        assert state.total == len(names) and state.scanned == len(names) and state.round == 1

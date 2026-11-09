"""Deterministic diagnostics; simulated positions only, no exchange order endpoints."""
import asyncio
import json
import time
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import config, db, worker, paper, main


def isolated(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, 'Session', factory)
    return factory


def scenario():
    return db.AutoSignal(symbol='BTC-USDT', interval='15m', side='LONG', entry=100,
                         stop=97, tp1=105, tp2=107, tp3=110,
                         result_json='{}', candle_time=900_000)


def test_diagnostics_saves_reason_counts_and_published_at(monkeypatch):
    factory = isolated(monkeypatch)
    worker._save_scan_diagnostics({'no_confirmed_signal': 12, 'insufficient_candles': 4}, ('BTC-USDT', db.now()))
    worker._save_scan_diagnostics({'no_confirmed_signal': 17, 'published': 1})
    with factory() as session:
        d = session.get(db.ScannerDiagnostics, 1)
        assert json.loads(d.reasons_json) == {'no_confirmed_signal': 17, 'published': 1}
        assert d.last_published_symbol == 'BTC-USDT'
        assert d.last_published_at is not None


def test_no_qualifying_signal_has_explicit_reason_and_no_paper_entry(monkeypatch):
    factory = isolated(monkeypatch)
    with factory.begin() as session:
        session.add(db.PaperAccount(user_id=12, enabled=True, cash=1000, initial_balance=1000))
    class Market:
        async def candles(self, symbol, interval):
            return []
    reasons = []
    accepted = asyncio.run(worker._scan_one(Market(), 'BTC-USDT', '15m', 100, int(time.time()*1000), reasons))
    assert not accepted
    assert reasons == ['insufficient_candles']
    with factory() as session:
        assert not session.scalars(select(db.PaperPosition)).all()
        assert not session.scalars(select(db.PaperDecision)).all()


def test_paper_attempt_records_reason_without_creating_fake_position(monkeypatch):
    factory = isolated(monkeypatch)
    monkeypatch.setattr(config, 'PAPER_MAX_POSITIONS', 0)
    with factory.begin() as session:
        session.add(db.PaperAccount(user_id=54, enabled=True, cash=1000, initial_balance=1000))
        sig = scenario()
        session.add(sig)
        session.flush()
        assert paper.open_for_signal(session, sig, 100) == []
    with factory() as session:
        decisions = session.scalars(select(db.PaperDecision)).all()
        assert len(decisions) == 1
        assert decisions[0].reason == 'position_limit_or_same_symbol'
        account = paper.account_snapshot(session, 54, {})
        assert account['positions'] == []
        assert account['latestDecisions'][0]['reason'] == 'position_limit_or_same_symbol'


def test_paper_success_is_audited(monkeypatch):
    factory = isolated(monkeypatch)
    with factory.begin() as session:
        session.add(db.PaperAccount(user_id=67, enabled=True, cash=1000, initial_balance=1000))
        sig = scenario()
        session.add(sig)
        session.flush()
        assert paper.open_for_signal(session, sig, 100)
    with factory() as session:
        assert session.scalar(select(db.PaperDecision)).reason == 'opened'
        assert len(session.scalars(select(db.PaperPosition)).all()) == 1


def test_auto_feed_api_has_persisted_diagnostics(monkeypatch):
    isolated(monkeypatch)
    worker._set_scan_progress(total=30, scanned=12, last_symbol='BTC-USDT')
    worker._save_scan_diagnostics({'no_confirmed_signal': 11, 'published': 1}, ('BTC-USDT', db.now()))
    class Market:
        async def contracts(self): return []
        async def ticker(self): return []
    monkeypatch.setattr(main, 'market', Market())
    result = asyncio.run(main.auto_signals(user_id=None))
    assert result['scanner']['reasons']['no_confirmed_signal'] == 11
    assert result['scanner']['lastPublishedSymbol'] == 'BTC-USDT'
    assert result['scanner']['lastPublishedAt'] is not None

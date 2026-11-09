"""Paper-trade archive: old signals remain queryable even after market eligibility changes."""
import asyncio
import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import db, main


def setup_db(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, 'Session', factory)
    return factory


def make_signal(symbol, status, side='LONG', reached=0, minutes=1):
    created = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return db.AutoSignal(symbol=symbol, interval='15m', side=side,
        entry=100, stop=97 if side == 'LONG' else 103,
        tp1=102 if side == 'LONG' else 98,
        tp2=104 if side == 'LONG' else 96,
        tp3=106 if side == 'LONG' else 94,
        status=status, tp_reached=reached,
        last_checked=int(created.timestamp() * 1000) + 60000,
        candle_time=int(created.timestamp() * 1000),
        result_json=json.dumps({'symbol': symbol, 'summary':'historical'}), created_at=created)


def run(**params):
    return asyncio.run(main.auto_history(**params))


def test_old_excluded_pairs_are_visible_and_paginated(monkeypatch):
    factory=setup_db(monkeypatch)
    with factory.begin() as session:
        session.add_all([make_signal('NCSKABNB2-USDT','STOP'),make_signal('BTC-USDT','TP3',reached=3,minutes=2),
                         make_signal('ETH-USDT','ACTIVE',minutes=3),make_signal('XRP-USDT','AMBIGUOUS',minutes=4)])
    p1=run(page=1,page_size=2)
    assert p1['total']==3  # only completed by default
    assert p1['hasMore']
    assert p1['stats']['total']==4
    assert p1['stats']['tp3']==1
    assert p1['stats']['stop']==1
    assert p1['stats']['tp3ShareOfKnownPercent']==50
    p2=run(page=2,page_size=2)
    assert not p2['hasMore']
    old=p2['items'][0]
    assert old['symbol']=='NCSKABNB2-USDT'  # no dynamic market eligibility filter
    assert old['finishedAtSource']=='last_checked_candle'
    assert old['terminalMovePercent']==-3.0
    assert run(outcome='ALL')['total']==4
    assert run(outcome='ACTIVE')['total']==1
    assert run(outcome='TP3',side='LONG')['items'][0]['symbol']=='BTC-USDT'
    assert run(outcome='STOP',symbol='NCSKA')['total']==1
    assert run(date_from='2026-11-05')['total']==0
    assert run(date_to='2026-11-04')['total']==3
    assert run(outcome='AMBIGUOUS')['items'][0]['terminalMovePercent'] is None


def test_empty_history_and_input_validation(monkeypatch):
    setup_db(monkeypatch)
    empty=run()
    assert empty['items']==[]
    assert empty['stats']['tp3ShareOfKnownPercent'] is None
    for kwargs in ({'page_size':999}, {'side':'BUY'}, {'date_from':'not-date'},
                   {'date_from':'2026-11-06','date_to':'2026-11-05'}):
        with pytest.raises(HTTPException):
            run(**kwargs)


def test_migration_adds_missing_column_without_dropping_old_rows(monkeypatch):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE auto_signals (id INTEGER PRIMARY KEY, symbol VARCHAR(32) NOT NULL)'))
        connection.execute(text("INSERT INTO auto_signals (id, symbol) VALUES (1,'BTC-USDT')"))
    monkeypatch.setattr(db,'engine',engine)
    db.init_db()
    assert 'finished_at' in {x['name'] for x in inspect(engine).get_columns('auto_signals')}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT symbol FROM auto_signals WHERE id=1')).scalar()=='BTC-USDT'

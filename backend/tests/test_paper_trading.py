"""Offline virtual ledger tests. NEVER connect to a private exchange/trading API."""
import asyncio
import datetime as dt
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import config, db, main, paper


def isolated(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, 'Session', factory)
    return factory


def signal(side='LONG'):
    return db.AutoSignal(symbol='BTC-USDT', interval='15m', side=side, entry=100,
        stop=97 if side=='LONG' else 103,
        tp1=105 if side=='LONG' else 98,
        tp2=107 if side=='LONG' else 96,
        tp3=110 if side=='LONG' else 94,
        candle_time=123456000, result_json=json.dumps({'side':side}))


def create_position(factory, side='LONG'):
    with factory.begin() as session:
        account=db.PaperAccount(user_id=123, enabled=True, cash=1000, initial_balance=1000)
        session.add(account)
        sig=signal(side)
        session.add(sig)
        session.flush()
        assert paper.open_for_signal(session, sig, 100)==[(123, 1)]
        # One event per user/signal (idempotence)
        assert paper.open_for_signal(session, sig, 100)==[]
    return 1


def test_disabled_never_enters_and_enabled_has_risk_cap(monkeypatch):
    factory=isolated(monkeypatch)
    with factory.begin() as session:
        session.add(db.PaperAccount(user_id=1,enabled=False,cash=1000,initial_balance=1000))
        session.add(db.PaperAccount(user_id=2,enabled=True,cash=1000,initial_balance=1000))
        sig=signal();session.add(sig);session.flush()
        assert paper.open_for_signal(session,sig,100)==[(2, 1)]
        assert paper.open_for_signal(session,sig,100)==[]
    with factory() as session:
        p=session.scalar(select(db.PaperPosition))
        account=session.get(db.PaperAccount,2)
        assert p.user_id==2
        assert p.quantity*p.entry_fill <= 200
        assert p.quantity*(p.entry_fill-p.stop) <= 10
        assert 790 < account.cash < 1000
        snapshot=paper.account_snapshot(session,2,{'BTC-USDT':100})
        assert snapshot['stats']['active']==1
        assert snapshot['equity'] < 1000  # modeled entry fee + slippage
        assert paper.account_snapshot(session,1,{'BTC-USDT':100})['positions']==[]


def test_partial_tp_then_stop_reconciles_virtual_balance(monkeypatch):
    factory=isolated(monkeypatch)
    create_position(factory)
    with factory.begin() as session:
        p=session.get(db.PaperPosition,1)
        t=p.last_checked
        assert paper.advance_candle(session,p,{'time':t+60_000,'low':99,'high':105.5,'close':104}) is None
        assert p.tp_reached==1 and p.status=='OPEN'
        assert pytest.approx(p.remaining/p.quantity,rel=1e-7)==2/3
        assert paper.advance_candle(session,p,{'time':t+120_000,'low':96.5,'high':104,'close':98})=='STOP'
        assert p.remaining==0 and p.margin_open==0
    with factory() as session:
        p=session.get(db.PaperPosition,1)
        account=session.get(db.PaperAccount,123)
        assert len(session.scalars(select(db.PaperFill)).all())==2
        assert account.cash==pytest.approx(1000+p.realized_pnl,abs=1e-8)
        assert p.status=='STOP'
        assert paper.account_snapshot(session,123,{})['equity']==pytest.approx(account.cash)


def test_ambiguous_candle_uses_conservative_stop(monkeypatch):
    factory=isolated(monkeypatch)
    create_position(factory)
    with factory.begin() as session:
        p=session.get(db.PaperPosition,1)
        assert paper.advance_candle(session,p,{'time':p.last_checked+60000,'low':96,'high':106,'close':100})=='AMBIGUOUS'
        assert p.tp_reached==0
        assert p.realized_pnl < 0
    with factory() as session:
        f=session.scalar(select(db.PaperFill))
        assert f.reason=='AMBIGUOUS_STOP'
        assert f.fill_price < 97  # conservative adverse slippage


def test_short_three_targets_and_no_real_api(monkeypatch):
    factory=isolated(monkeypatch)
    create_position(factory, side='SHORT')
    with factory.begin() as session:
        p=session.get(db.PaperPosition,1)
        assert paper.advance_candle(session,p,{'time':p.last_checked+60000,'low':93,'high':101,'close':95})=='TP3'
        assert p.tp_reached==3 and p.remaining==0
        assert p.realized_pnl>0
    with factory() as session:
        assert [f.reason for f in session.scalars(select(db.PaperFill).order_by(db.PaperFill.id))]==['TP1','TP2','TP3']
        assert session.get(db.PaperAccount,123).cash>1000


def test_missing_minute_freezes_position_instead_of_inventing_outcome(monkeypatch):
    factory=isolated(monkeypatch)
    create_position(factory)
    with factory.begin() as session:
        p=session.get(db.PaperPosition,1)
        assert paper.advance_candle(session,p,{'time':p.last_checked+120000,'low':90,'high':110})=='DATA_GAP'
        assert p.remaining==p.quantity and p.realized_pnl<0
        assert p.status=='DATA_GAP'
        paper.manual_close(session,p,99)
        assert p.status=='MANUAL' and p.margin_open==0


def test_rest_toggle_and_reset_do_not_clear_open_positions(monkeypatch):
    factory=isolated(monkeypatch)
    assert asyncio.run(main.paper_config(main.PaperConfigBody(enabled=True),user_id=7))['enabled']
    with factory.begin() as session:
        sig=signal();session.add(sig);session.flush()
        assert paper.open_for_signal(session,sig,100)==[(7, 1)]
    asyncio.run(main.paper_config(main.PaperConfigBody(enabled=False),user_id=7))
    with pytest.raises(HTTPException):
        asyncio.run(main.paper_reset(user_id=7))
    with factory.begin() as session:
        paper.manual_close(session,session.get(db.PaperPosition,1),99)
    assert asyncio.run(main.paper_reset(user_id=7))=={'ok':True,'balance':1000.0}
    with factory() as session:
        assert session.get(db.PaperAccount,7).cash==1000
        assert session.scalars(select(db.PaperPosition)).all()==[]
        assert session.scalars(select(db.PaperFill)).all()==[]


def test_scanner_publishes_new_signal_and_opens_enabled_demo(monkeypatch):
    from app import worker
    factory=isolated(monkeypatch)
    with factory.begin() as session:
        session.add(db.PaperAccount(user_id=37,enabled=True,cash=1000,initial_balance=1000))
    step=900000
    now_ms=int(dt.datetime.now(dt.timezone.utc).timestamp()*1000)//step*step + 30000
    candles=[{'time':now_ms-30000-(i+1)*step,'open':100,'high':101,'low':99,
              'close':100,'volume':100} for i in range(310)]
    candles.reverse()
    class Fake:
        async def candles(self, symbol, interval, limit=310): return candles
    result={'symbol':'BTC-USDT','interval':'15m','side':'LONG','price':100,
            'entry':100,'stopLoss':97,'takeProfits':[105,107,110],
            'metrics':{'atr':1},'summary':'virtual','reasons':[],'risks':[]}
    monkeypatch.setattr(worker,'analyze',lambda *args,**kwargs:result)
    monkeypatch.setattr(config,'OPENAI_API_KEY','')
    assert asyncio.run(worker._scan_one(Fake(),'BTC-USDT','15m',100,now_ms))
    assert not asyncio.run(worker._scan_one(Fake(),'BTC-USDT','15m',100,now_ms))
    with factory() as session:
        assert session.scalar(select(db.PaperPosition).where(db.PaperPosition.user_id==37)) is not None
        assert len(session.scalars(select(db.PaperPosition)).all())==1


def test_paper_api_requires_telegram_auth():
    from fastapi.testclient import TestClient
    client=TestClient(main.app, raise_server_exceptions=False)
    assert client.get('/api/paper').status_code==401
    assert client.post('/api/paper/config',json={'enabled':True}).status_code==401
    assert client.post('/api/paper/reset').status_code==401

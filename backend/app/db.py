"""Persisted history, favorites, settings, watches and alerts."""
import datetime as dt
from sqlalchemy import create_engine, ForeignKey, Integer, BigInteger, Float, String, DateTime, Boolean, Text, UniqueConstraint, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from . import config

url = config.DATABASE_URL
if url.startswith('postgres://'):
    url = 'postgresql+psycopg://' + url[len('postgres://'):]
elif url.startswith('postgresql://'):
    url = 'postgresql+psycopg://' + url[len('postgresql://'):]
engine = create_engine(url, pool_pre_ping=True, connect_args={'check_same_thread': False} if url.startswith('sqlite:') else {})
Session = sessionmaker(bind=engine, expire_on_commit=False)


def now():
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = 'people'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    interval: Mapped[str] = mapped_column(String(8), default='15m')
    language: Mapped[str] = mapped_column(String(5), default='ru')
    theme: Mapped[str] = mapped_column(String(8), default='dark')
    notifications: Mapped[bool] = mapped_column(Boolean, default=True)


class Favorite(Base):
    __tablename__ = 'favorites'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint('user_id', 'symbol'),)


class Signal(Base):
    __tablename__ = 'signals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(6))
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp1: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp2: Mapped[float | None] = mapped_column(Float, nullable=True)
    tp3: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(12), default='ACTIVE')
    tp_reached: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(Text)
    last_checked: Mapped[int] = mapped_column(Integer, default=0)  # candle open ms
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class AutoSignal(Base):
    """Public, read-only simulated scenarios. Never represents an actual order."""
    __tablename__ = 'auto_signals'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    interval: Mapped[str] = mapped_column(String(8), default='15m')
    side: Mapped[str] = mapped_column(String(6))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default='ACTIVE')
    tp_reached: Mapped[int] = mapped_column(Integer, default=0)
    last_checked: Mapped[int] = mapped_column(BigInteger, default=0)
    candle_time: Mapped[int] = mapped_column(BigInteger)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('symbol', 'interval', 'candle_time'),)


class AutoSignalSubscription(Base):
    """Explicit opt-in for Telegram messages about global auto scenarios."""
    __tablename__ = 'auto_signal_subscriptions'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class ScannerState(Base):
    """Observable progress of a single Railway scanner instance."""
    __tablename__ = 'scanner_state'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    scanned: Mapped[int] = mapped_column(Integer, default=0)
    round: Mapped[int] = mapped_column(Integer, default=0)
    last_symbol: Mapped[str] = mapped_column(String(32), default='')
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(String(200), default='')


class ScannerDiagnostics(Base):
    """Latest full or partial scan's *real* rejection counts, not a performance claim."""
    __tablename__ = 'scanner_diagnostics'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reasons_json: Mapped[str] = mapped_column(Text, default='{}')
    last_published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_published_symbol: Mapped[str] = mapped_column(String(32), default='')
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class PaperDecision(Base):
    """Audit whether an actual new public scenario led to a virtual entry."""
    __tablename__ = 'paper_decisions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    auto_signal_id: Mapped[int] = mapped_column(Integer, ForeignKey('auto_signals.id'))
    reason: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('user_id', 'auto_signal_id'),)


class PumpEvent(Base):
    """Observed rapid price movement, not a prediction or trading recommendation."""
    __tablename__ = 'pump_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(5))  # PUMP / DUMP
    change_pct: Mapped[float] = mapped_column(Float)
    start_price: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    volume_ratio: Mapped[float] = mapped_column(Float)
    turnover_usdt: Mapped[float] = mapped_column(Float)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class PumpSubscription(Base):
    """Private-chat pump/dump alerts are opt-in, independent of ordinary signals."""
    __tablename__ = 'pump_subscriptions'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class Alert(Base):
    __tablename__ = 'alerts'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    target_price: Mapped[float] = mapped_column(Float)
    baseline_price: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Watch(Base):
    __tablename__ = 'watches'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8), default='15m')
    last_side: Mapped[str] = mapped_column(String(6), default='WAIT')
    __table_args__ = (UniqueConstraint('user_id', 'symbol', 'interval'),)



class PaperAccount(Base):
    """Opt-in personal ledger. No exchange credentials or real order placement."""
    __tablename__ = 'paper_accounts'
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    cash: Mapped[float] = mapped_column(Float, default=1000.0)
    initial_balance: Mapped[float] = mapped_column(Float, default=1000.0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class PaperPosition(Base):
    """1x synthetic long/short P&L; deposited margin is simulated, not borrowed."""
    __tablename__ = 'paper_positions'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    auto_signal_id: Mapped[int] = mapped_column(Integer, ForeignKey('auto_signals.id'))
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[str] = mapped_column(String(6))
    entry_quote: Mapped[float] = mapped_column(Float)
    entry_fill: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    quantity: Mapped[float] = mapped_column(Float)
    remaining: Mapped[float] = mapped_column(Float)
    margin_open: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0)
    tp_reached: Mapped[int] = mapped_column(Integer, default=0)
    last_checked: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default='OPEN')
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('user_id', 'auto_signal_id'),)


class PaperFill(Base):
    __tablename__ = 'paper_fills'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position_id: Mapped[int] = mapped_column(Integer, ForeignKey('paper_positions.id'), index=True)
    reason: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    fill_price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    candle_time: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


def init_db():
    # Upgrade previous Railway PostgreSQL databases without dropping saved records.
    # Existing rows retain NULL; the API can show a last-candle estimate for old outcomes.
    inspector = inspect(engine)
    if 'auto_signals' in inspector.get_table_names():
        columns = {c['name'] for c in inspector.get_columns('auto_signals')}
        if 'finished_at' not in columns:
            with engine.begin() as conn:
                if engine.dialect.name == 'postgresql':
                    conn.execute(text('ALTER TABLE auto_signals ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ'))
                else:
                    conn.execute(text('ALTER TABLE auto_signals ADD COLUMN finished_at DATETIME'))
    Base.metadata.create_all(engine)


def get_person(session, user_id: int) -> Person:
    person = session.get(Person, user_id)
    if not person:
        person = Person(user_id=user_id)
        session.add(person)
        session.flush()
    return person


def signal_out(s: Signal) -> dict:
    return {'id': s.id, 'symbol': s.symbol, 'interval': s.interval, 'side': s.side,
            'entry': s.entry, 'stopLoss': s.stop, 'takeProfits': [x for x in [s.tp1,s.tp2,s.tp3] if x is not None],
            'status': ('TP'+str(s.tp_reached) if s.status == 'ACTIVE' and s.tp_reached else s.status), 'tpReached': s.tp_reached, 'createdAt': s.created_at.isoformat(), 'result': __import__('json').loads(s.result_json)}


def auto_signal_out(s: AutoSignal) -> dict:
    import json
    return {'id': s.id, 'symbol': s.symbol, 'interval': s.interval, 'side': s.side,
            'entry': s.entry, 'stopLoss': s.stop, 'takeProfits': [s.tp1, s.tp2, s.tp3],
            'status': s.status, 'tpReached': s.tp_reached,
            'createdAt': s.created_at.isoformat(), 'result': json.loads(s.result_json)}


def pump_event_out(event: PumpEvent) -> dict:
    return {'id': event.id, 'symbol': event.symbol, 'direction': event.direction,
            'changePercent': event.change_pct, 'startPrice': event.start_price,
            'price': event.price, 'volumeRatio': event.volume_ratio,
            'turnoverUsdt': event.turnover_usdt, 'windowMinutes': 5,
            'occurredAt': event.occurred_at.isoformat()}

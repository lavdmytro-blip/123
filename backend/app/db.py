"""Persisted history, favorites, settings, watches and alerts."""
import datetime as dt
from sqlalchemy import create_engine, ForeignKey, Integer, BigInteger, Float, String, DateTime, Boolean, Text, UniqueConstraint
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


def init_db():
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

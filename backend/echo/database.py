from datetime import datetime, timezone
import time
from uuid import uuid4
from sqlalchemy import create_engine, String, Text, Integer, BigInteger, Boolean, ForeignKey, UniqueConstraint, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def now_ts(): return int(datetime.now(timezone.utc).timestamp())
def uid(): return str(uuid4())
class Base(DeclarativeBase): pass
class Project(Base):
    __tablename__='projects'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(120))
class Membership(Base):
    __tablename__='project_members'
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),primary_key=True)
    user_id: Mapped[str]=mapped_column(String(128),primary_key=True)
    role: Mapped[str]=mapped_column(String(16),default='owner')
class Study(Base):
    __tablename__='studies'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'),index=True)
    title: Mapped[str]=mapped_column(String(120))
    pathway: Mapped[str]=mapped_column(Text)
    status: Mapped[str]=mapped_column(String(20),default='draft')
    version: Mapped[int]=mapped_column(Integer,default=1)
    approved_at: Mapped[int|None]=mapped_column(Integer,nullable=True)
class Invitation(Base):
    __tablename__='invitations'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    study_id: Mapped[str]=mapped_column(ForeignKey('studies.id'),index=True)
    token_hash: Mapped[str]=mapped_column(String(64),unique=True)
    kind: Mapped[str]=mapped_column(String(20))
    max_uses: Mapped[int]=mapped_column(Integer)
    uses: Mapped[int]=mapped_column(Integer,default=0)
    bound_participant_id: Mapped[str|None]=mapped_column(String(36),nullable=True)
    expires_at: Mapped[int]=mapped_column(Integer)
    revoked: Mapped[bool]=mapped_column(Boolean,default=False)
class Participant(Base):
    __tablename__='participants'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    phone_hash: Mapped[str]=mapped_column(String(64),unique=True)
    phone_cipher: Mapped[str]=mapped_column(Text)
    opted_out: Mapped[bool]=mapped_column(Boolean,default=False)
    last_inbound_at: Mapped[int]=mapped_column(Integer,default=0)
    active_interview_id: Mapped[str|None]=mapped_column(String(36),nullable=True)
class Interview(Base):
    __tablename__='interviews'
    __table_args__=(UniqueConstraint('study_id','participant_id'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    study_id: Mapped[str]=mapped_column(ForeignKey('studies.id'),index=True)
    participant_id: Mapped[str]=mapped_column(ForeignKey('participants.id'),index=True)
    status: Mapped[str]=mapped_column(String(30),default='started')
    pathway_cipher: Mapped[str]=mapped_column(Text)
    state_cipher: Mapped[str]=mapped_column(Text)
    consent_cipher: Mapped[str]=mapped_column(Text)
    created_at: Mapped[int]=mapped_column(Integer,default=now_ts)
    updated_at: Mapped[int]=mapped_column(Integer,default=now_ts)
    expires_at: Mapped[int]=mapped_column(Integer)
class InboundEvent(Base):
    __tablename__='inbound_events'
    id: Mapped[str]=mapped_column(String(255),primary_key=True)
    participant_id: Mapped[str]=mapped_column(ForeignKey('participants.id'),index=True)
    payload_cipher: Mapped[str]=mapped_column(Text)
    status: Mapped[str]=mapped_column(String(20),default='queued',index=True)
    error_code: Mapped[str|None]=mapped_column(String(80),nullable=True)
    created_at: Mapped[int]=mapped_column(Integer,default=now_ts)
    received_order: Mapped[int]=mapped_column(BigInteger,default=time.time_ns)
    expires_at: Mapped[int]=mapped_column(Integer)
class Turn(Base):
    __tablename__='turns'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    interview_id: Mapped[str]=mapped_column(ForeignKey('interviews.id',ondelete='CASCADE'),index=True)
    event_id: Mapped[str]=mapped_column(String(255),unique=True)
    sequence: Mapped[int]=mapped_column(Integer,default=0)
    payload_cipher: Mapped[str]=mapped_column(Text)
    created_at: Mapped[int]=mapped_column(Integer,default=now_ts)
class Outbox(Base):
    __tablename__='outbox'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    event_id: Mapped[str]=mapped_column(String(255),unique=True)
    participant_id: Mapped[str]=mapped_column(ForeignKey('participants.id'),index=True)
    interview_id: Mapped[str|None]=mapped_column(String(36),nullable=True)
    text_cipher: Mapped[str]=mapped_column(Text)
    status: Mapped[str]=mapped_column(String(30),default='pending',index=True)
    provider_id: Mapped[str|None]=mapped_column(String(255),nullable=True,unique=True)
    delivery_at: Mapped[int]=mapped_column(Integer,default=0)
    error_code: Mapped[str|None]=mapped_column(String(80),nullable=True)
    control_ack: Mapped[bool]=mapped_column(Boolean,default=False)
    created_at: Mapped[int]=mapped_column(Integer,default=now_ts)
    created_order: Mapped[int]=mapped_column(BigInteger,default=time.time_ns)
    expires_at: Mapped[int]=mapped_column(Integer)

class DeliveryEvent(Base):
    __tablename__='delivery_events'
    id: Mapped[str]=mapped_column(String(64),primary_key=True)
    provider_id: Mapped[str]=mapped_column(String(255),index=True)
    status: Mapped[str]=mapped_column(String(30))
    timestamp: Mapped[int]=mapped_column(Integer)
    error_code: Mapped[int|None]=mapped_column(Integer,nullable=True)
    expires_at: Mapped[int]=mapped_column(Integer,index=True)

def database(url):
    kwargs={'connect_args':{'check_same_thread':False,'timeout':15}} if url.startswith('sqlite') else {'pool_pre_ping':True,'pool_size':2,'max_overflow':1,'pool_timeout':10}
    engine=create_engine(url,**kwargs)
    if url.startswith('sqlite'):
        @event.listens_for(engine,'connect')
        def configure(dbapi_connection,_):
            dbapi_connection.execute('PRAGMA foreign_keys=ON')
            dbapi_connection.execute('PRAGMA journal_mode=WAL')
    return engine,sessionmaker(bind=engine,expire_on_commit=False)

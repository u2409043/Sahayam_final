"""
Database setup for Sahayam.

Uses SQLite for the prototype so the whole stack runs with zero external
services. Swapping to PostgreSQL + PostGIS later only means changing
SQLALCHEMY_DATABASE_URL and the geometry columns -- the rest of the app
(models, queries, API) does not need to change.
"""
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./sahayam.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class HelpRequest(Base):
    """A single request for help, submitted from any channel."""

    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, index=True)

    # Who / how
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    channel = Column(String, default="app")  # app | whatsapp | ivr | sms
    language = Column(String, default="ml")  # ml (Malayalam) | en

    # What
    description = Column(Text, nullable=False)
    category = Column(String, default="general")  # rescue | medical | food | shelter | general
    has_elderly = Column(Integer, default=0)
    has_children = Column(Integer, default=0)
    has_medical_need = Column(Integer, default=0)

    # Where
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    location_text = Column(String, nullable=True)

    # Triage output
    urgency_score = Column(Float, default=0.0)  # 0-100, higher = more urgent
    urgency_label = Column(String, default="medium")  # low | medium | high | critical
    ml_confidence = Column(Float, default=0.0)

    # Lifecycle
    status = Column(String, default="pending")  # pending | assigned | in_progress | resolved
    assigned_to = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    """An admin or volunteer login. Citizens never authenticate -- request
    intake (POST /api/requests) stays open to anyone."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "admin" | "volunteer"
    name = Column(String, nullable=False)

    # Volunteers only: their base location, used for proximity sorting.
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

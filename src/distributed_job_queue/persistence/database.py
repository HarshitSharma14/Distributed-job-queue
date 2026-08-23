"""SQLAlchemy engine and session factory."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from distributed_job_queue.common.config import load_settings

settings = load_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionFactory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

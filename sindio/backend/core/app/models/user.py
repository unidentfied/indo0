from sqlalchemy import Column, Integer, String, Boolean, DateTime, func
from ..ingestion.models import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_paid = Column(Boolean, default=False, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_trial = Column(Boolean, default=True, nullable=False)
    trial_expires_at = Column(DateTime(timezone=True), nullable=True)
    subscription_type = Column(String(20), nullable=True)  # 'monthly' or 'yearly'
    subscription_price = Column(Integer, nullable=True)  # price in KES
    subscription_start = Column(DateTime(timezone=True), nullable=True)
    subscription_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

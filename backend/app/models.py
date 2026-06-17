from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    openid: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    session_key: Mapped[Optional[str]] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(80), default="智搭用户")
    avatar: Mapped[str] = mapped_column(Text, default="")
    role: Mapped[str] = mapped_column(String(20), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    style_preference: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    children: Mapped[List["Child"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Child(Base):
    __tablename__ = "children"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    nickname: Mapped[str] = mapped_column(String(80), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), nullable=False)
    birthday: Mapped[date] = mapped_column(Date, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    skin_tone: Mapped[str] = mapped_column(String(20), default="")
    photo_url: Mapped[str] = mapped_column(Text, default="")
    avatar_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="children")
    clothing: Mapped[List["Clothing"]] = relationship(
        back_populates="child",
        cascade="all, delete-orphan",
    )
    diaries: Mapped[List["OutfitDiary"]] = relationship(
        back_populates="child",
        cascade="all, delete-orphan",
    )


class Clothing(Base):
    __tablename__ = "clothing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    photo_url: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    sub_type: Mapped[str] = mapped_column(String(60), default="")
    main_color: Mapped[str] = mapped_column(String(40), nullable=False)
    pattern: Mapped[str] = mapped_column(String(40), default="solid")
    season: Mapped[list[str]] = mapped_column(JSON, default=list)
    thickness: Mapped[str] = mapped_column(String(40), nullable=False)
    style_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    brand: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")
    wear_count: Mapped[int] = mapped_column(Integer, default=0)
    last_worn_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    child: Mapped[Child] = relationship(back_populates="clothing")


class UploadAsset(Base):
    __tablename__ = "upload_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutfitRecommendation(Base):
    __tablename__ = "outfit_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    cache_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    request_signature: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class OutfitDiary(Base):
    __tablename__ = "outfit_diaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    child_id: Mapped[int] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    clothing_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    scene: Mapped[str] = mapped_column(String(60), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    mood: Mapped[str] = mapped_column(String(60), default="")
    rating: Mapped[int] = mapped_column(Integer, default=0)
    actual_photo_url: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    child: Mapped[Child] = relationship(back_populates="diaries")

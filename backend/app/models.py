from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Float, DateTime, ForeignKey, UniqueConstraint, func
)
from sqlalchemy.orm import relationship
from backend.app.db import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # 'user' or 'admin'
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    bookings = relationship("Booking", back_populates="user")


class Movie(Base):
    __tablename__ = "movies"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    duration_minutes = Column(Integer, nullable=False)
    poster_url = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    shows = relationship("Show", back_populates="movie", cascade="all, delete-orphan")


class Show(Base):
    __tablename__ = "shows"

    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    screen_name = Column(String(100), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    price = Column(Float, default=250.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    movie = relationship("Movie", back_populates="shows")
    seats = relationship("ShowSeat", back_populates="show", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="show")


class ShowSeat(Base):
    __tablename__ = "show_seats"

    id = Column(Integer, primary_key=True, index=True)
    show_id = Column(Integer, ForeignKey("shows.id", ondelete="CASCADE"), nullable=False, index=True)
    seat_label = Column(String(10), nullable=False, index=True)
    status = Column(String(20), default="AVAILABLE", nullable=False)  # AVAILABLE, LOCKED, BOOKED
    locked_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    show = relationship("Show", back_populates="seats")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("show_id", "seat_label", name="uq_show_seat_label"),
    )


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    show_id = Column(Integer, ForeignKey("shows.id", ondelete="CASCADE"), nullable=False, index=True)
    seat_label = Column(String(10), nullable=False)
    booking_reference = Column(String(100), unique=True, index=True, nullable=False)
    status = Column(String(20), default="CONFIRMED", nullable=False)  # CONFIRMED, CANCELLED
    total_amount = Column(Float, default=250.0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    user = relationship("User", back_populates="bookings")
    show = relationship("Show", back_populates="bookings")

    # Final safety net: strictly prevent duplicate confirmed bookings for same show and seat
    __table_args__ = (
        UniqueConstraint("show_id", "seat_label", name="uq_bookings_show_seat"),
    )

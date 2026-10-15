import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Booking, Show, ShowSeat, User
from backend.app.auth import get_current_user

router = APIRouter()

class ConfirmBookingRequest(BaseModel):
    show_id: int
    seats: List[str] = Field(..., min_length=1, description="List of seat labels to confirm")
    payment_token: Optional[str] = Field("fake_payment_token_success", description="Payment token from payment step")

class BookingItemSchema(BaseModel):
    id: int
    booking_reference: str
    show_id: int
    movie_title: str
    screen_name: str
    show_time: datetime
    seat_label: str
    price: float
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class ConfirmBookingResponse(BaseModel):
    message: str
    booking_reference: str
    show_id: int
    seats: List[str]
    total_amount: float
    status: str

@router.post("/confirm", response_model=ConfirmBookingResponse)
def confirm_booking(
    request: ConfirmBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify show exists
    show = db.query(Show).filter(Show.id == request.show_id).first()
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show with ID {request.show_id} not found"
        )

    requested_labels = [s.strip().upper() for s in request.seats if s.strip()]
    if not requested_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid seat label must be provided"
        )

    # 1. Deterministic ordering by seat_label to prevent deadlocks
    sorted_labels = sorted(list(set(requested_labels)))

    try:
        # 2. Open transaction: SELECT ... FOR UPDATE on requested seats
        seats = (
            db.query(ShowSeat)
            .filter(
                ShowSeat.show_id == request.show_id,
                ShowSeat.seat_label.in_(sorted_labels)
            )
            .order_by(ShowSeat.seat_label.asc())
            .with_for_update()
            .all()
        )

        if len(seats) != len(sorted_labels):
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more requested seats do not exist for this show"
            )

        now = datetime.now(timezone.utc)

        # 3. Check that the user still holds every lock and it has not expired
        for seat in seats:
            if seat.status != "LOCKED":
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat {seat.seat_label} is not locked (status: {seat.status})"
                )

            if seat.locked_by != current_user.id:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat {seat.seat_label} is not locked by you"
                )

            if seat.locked_until is None:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat {seat.seat_label} has no active lock timestamp"
                )

            lu = seat.locked_until
            if lu.tzinfo is None:
                lu = lu.replace(tzinfo=timezone.utc)
            if lu <= now:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Lock on seat {seat.seat_label} has expired"
                )

        # 4. Insert bookings and set seats to BOOKED
        booking_ref = f"BK-{uuid.uuid4().hex[:8].upper()}"
        total_amount = len(seats) * show.price

        for seat in seats:
            booking = Booking(
                user_id=current_user.id,
                show_id=request.show_id,
                seat_label=seat.seat_label,
                booking_reference=booking_ref,
                status="CONFIRMED",
                total_amount=show.price
            )
            db.add(booking)

            # Update seat status
            seat.status = "BOOKED"
            seat.locked_by = None
            seat.locked_until = None

        # 5. Flush and Commit: If UNIQUE(show_id, seat_label) constraint fails, rollback and return 409
        db.commit()

        return ConfirmBookingResponse(
            message="Booking confirmed successfully!",
            booking_reference=booking_ref,
            show_id=request.show_id,
            seats=sorted_labels,
            total_amount=total_amount,
            status="CONFIRMED"
        )

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Double booking prevented by unique constraint safety net"
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Booking confirmation failed: {str(e)}"
        )

@router.get("/me", response_model=List[BookingItemSchema])
def get_my_bookings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    bookings = (
        db.query(Booking)
        .filter(Booking.user_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    result = []
    for b in bookings:
        # Clean seat label if prefixed with CANCELLED
        clean_label = b.seat_label
        if clean_label.startswith("CANCELLED_"):
            parts = clean_label.split("_", 2)
            if len(parts) >= 3:
                clean_label = parts[2]

        show = b.show
        movie_title = show.movie.title if show and show.movie else "Unknown"
        screen_name = show.screen_name if show else "Unknown"
        show_time = show.start_time if show else datetime.now(timezone.utc)

        result.append(BookingItemSchema(
            id=b.id,
            booking_reference=b.booking_reference,
            show_id=b.show_id,
            movie_title=movie_title,
            screen_name=screen_name,
            show_time=show_time,
            seat_label=clean_label,
            price=b.total_amount,
            status=b.status,
            created_at=b.created_at
        ))

    return result

@router.post("/{id}/cancel")
def cancel_booking(
    id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    booking = (
        db.query(Booking)
        .filter(Booking.id == id, Booking.user_id == current_user.id)
        .first()
    )

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with ID {id} not found"
        )

    if booking.status == "CANCELLED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking is already cancelled"
        )

    clean_label = booking.seat_label
    if clean_label.startswith("CANCELLED_"):
        parts = clean_label.split("_", 2)
        if len(parts) >= 3:
            clean_label = parts[2]

    try:
        # Free the seat back to AVAILABLE
        seat = (
            db.query(ShowSeat)
            .filter(
                ShowSeat.show_id == booking.show_id,
                ShowSeat.seat_label == clean_label
            )
            .with_for_update()
            .first()
        )

        if seat:
            seat.status = "AVAILABLE"
            seat.locked_by = None
            seat.locked_until = None

        booking.status = "CANCELLED"
        # Update seat_label to release the UNIQUE(show_id, seat_label) constraint
        booking.seat_label = f"CANCELLED_{booking.id}_{clean_label}"

        db.commit()

        return {
            "message": "Booking cancelled successfully. Seat has been freed.",
            "booking_id": id,
            "seat_label": clean_label,
            "status": "CANCELLED"
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel booking: {str(e)}"
        )

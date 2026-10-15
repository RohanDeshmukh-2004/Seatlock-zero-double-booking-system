from datetime import datetime, timedelta, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Show, ShowSeat, User
from backend.app.auth import get_current_user

router = APIRouter()

class SeatLockRequest(BaseModel):
    seats: List[str] = Field(..., min_length=1, description="List of seat labels to lock (e.g. ['A1', 'A2'])")

class SeatLockResponse(BaseModel):
    message: str
    show_id: int
    seats: List[str]
    locked_until: datetime

class SeatUnlockRequest(BaseModel):
    seats: List[str] = Field(..., min_length=1, description="List of seat labels to unlock")

class SeatUnlockResponse(BaseModel):
    message: str
    unlocked_seats: List[str]

@router.post("/shows/{id}/lock", response_model=SeatLockResponse)
def lock_seats(
    id: int,
    request: SeatLockRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify show exists
    show = db.query(Show).filter(Show.id == id).first()
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show with ID {id} not found"
        )

    # Clean and deduplicate seat labels
    requested_labels = [s.strip().upper() for s in request.seats if s.strip()]
    if not requested_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid seat label must be provided"
        )

    # 1. ORDER requested seats by seat_label to prevent database deadlocks
    sorted_seat_labels = sorted(list(set(requested_labels)))

    try:
        # 2. Open transaction and run SELECT ... FOR UPDATE ordered by seat_label
        locked_seats = (
            db.query(ShowSeat)
            .filter(
                ShowSeat.show_id == id,
                ShowSeat.seat_label.in_(sorted_seat_labels)
            )
            .order_by(ShowSeat.seat_label.asc())
            .with_for_update()
            .all()
        )

        # Check if all requested seats exist for this show
        if len(locked_seats) != len(sorted_seat_labels):
            found_labels = {seat.seat_label for seat in locked_seats}
            missing = set(sorted_seat_labels) - found_labels
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid seat labels for this show: {list(missing)}"
            )

        now = datetime.now(timezone.utc)

        # 3. Check availability for ALL seats: all or none
        for seat in locked_seats:
            is_free = False

            if seat.status == "AVAILABLE":
                is_free = True
            elif seat.status == "LOCKED":
                if seat.locked_until is None:
                    is_free = True
                else:
                    lu = seat.locked_until
                    if lu.tzinfo is None:
                        lu = lu.replace(tzinfo=timezone.utc)
                    # A seat is free ONLY if status is AVAILABLE or locked_until is in the past
                    if lu <= now:
                        is_free = True

            # If any seat is taken/booked, roll back and return 409
            if not is_free:
                db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Seat {seat.seat_label} is currently not available"
                )

        # 4. Set status LOCKED, locked_by = user, locked_until = now + 5 minutes
        lock_expiry = now + timedelta(minutes=5)
        for seat in locked_seats:
            seat.status = "LOCKED"
            seat.locked_by = current_user.id
            seat.locked_until = lock_expiry

        db.commit()

        return SeatLockResponse(
            message="Seats locked successfully for 5 minutes",
            show_id=id,
            seats=[seat.seat_label for seat in locked_seats],
            locked_until=lock_expiry
        )

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to lock seats: {str(e)}"
        )

@router.post("/shows/{id}/unlock", response_model=SeatUnlockResponse)
def unlock_seats(
    id: int,
    request: SeatUnlockRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify show exists
    show = db.query(Show).filter(Show.id == id).first()
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show with ID {id} not found"
        )

    requested_labels = [s.strip().upper() for s in request.seats if s.strip()]
    if not requested_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one valid seat label must be provided"
        )

    sorted_seat_labels = sorted(list(set(requested_labels)))

    try:
        # SELECT ... FOR UPDATE to safely release locks held by this user
        seats = (
            db.query(ShowSeat)
            .filter(
                ShowSeat.show_id == id,
                ShowSeat.seat_label.in_(sorted_seat_labels),
                ShowSeat.locked_by == current_user.id,
                ShowSeat.status == "LOCKED"
            )
            .order_by(ShowSeat.seat_label.asc())
            .with_for_update()
            .all()
        )

        unlocked_labels = []
        for seat in seats:
            seat.status = "AVAILABLE"
            seat.locked_by = None
            seat.locked_until = None
            unlocked_labels.append(seat.seat_label)

        db.commit()

        return SeatUnlockResponse(
            message="Seats unlocked successfully",
            unlocked_seats=unlocked_labels
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to unlock seats: {str(e)}"
        )

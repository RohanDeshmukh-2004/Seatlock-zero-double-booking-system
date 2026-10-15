from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Movie, Show, ShowSeat

router = APIRouter()

# Pydantic Schemas
class MovieSchema(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    duration_minutes: int
    poster_url: Optional[str] = None

    class Config:
        from_attributes = True

class ShowSchema(BaseModel):
    id: int
    movie_id: int
    screen_name: str
    start_time: datetime
    price: float
    movie: Optional[MovieSchema] = None

    class Config:
        from_attributes = True

class SeatSchema(BaseModel):
    id: int
    show_id: int
    seat_label: str
    status: str  # AVAILABLE, LOCKED, BOOKED
    price: float
    locked_until: Optional[datetime] = None

    class Config:
        from_attributes = True

@router.get("/movies", response_model=List[MovieSchema])
def get_movies(db: Session = Depends(get_db)):
    movies = db.query(Movie).order_by(Movie.title).all()
    return movies

@router.get("/shows", response_model=List[ShowSchema])
def get_shows(
    movie_id: Optional[int] = Query(None, description="Filter shows by movie ID"),
    db: Session = Depends(get_db)
):
    query = db.query(Show)
    if movie_id is not None:
        query = query.filter(Show.movie_id == movie_id)
    shows = query.order_by(Show.start_time).all()
    return shows

@router.get("/shows/{id}", response_model=ShowSchema)
def get_show_by_id(id: int, db: Session = Depends(get_db)):
    show = db.query(Show).filter(Show.id == id).first()
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show with ID {id} not found"
        )
    return show

@router.get("/shows/{id}/seats", response_model=List[SeatSchema])
def get_show_seats(id: int, db: Session = Depends(get_db)):
    show = db.query(Show).filter(Show.id == id).first()
    if not show:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Show with ID {id} not found"
        )

    now = datetime.now(timezone.utc)
    seats = db.query(ShowSeat).filter(ShowSeat.show_id == id).all()

    # Natural sort by row letter then seat number (e.g. A1, A2, ... A10, B1)
    def seat_sort_key(s: ShowSeat):
        row = s.seat_label[0]
        col = int(s.seat_label[1:]) if s.seat_label[1:].isdigit() else 0
        return (row, col)

    sorted_seats = sorted(seats, key=seat_sort_key)

    result = []
    for seat in sorted_seats:
        effective_status = seat.status
        # Expired locks need no cleanup job. The time check handles them:
        if seat.status == "LOCKED" and seat.locked_until:
            locked_until_utc = seat.locked_until
            if locked_until_utc.tzinfo is None:
                locked_until_utc = locked_until_utc.replace(tzinfo=timezone.utc)
            if locked_until_utc <= now:
                effective_status = "AVAILABLE"

        result.append(SeatSchema(
            id=seat.id,
            show_id=seat.show_id,
            seat_label=seat.seat_label,
            status=effective_status,
            price=show.price,
            locked_until=seat.locked_until
        ))

    return result

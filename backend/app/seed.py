import os
import sys
from datetime import datetime, timedelta, timezone

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import bcrypt
from backend.app.db import SessionLocal, engine, Base
from backend.app.models import User, Movie, Show, ShowSeat

def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

def seed():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("[*] Starting database seeding for SeatLock...")

        # 1. Seed Users (if not exists)
        admin = db.query(User).filter_by(email="admin@seatlock.com").first()
        if not admin:
            admin = User(
                email="admin@seatlock.com",
                password_hash=hash_password("admin123"),
                role="admin"
            )
            db.add(admin)

        test_user = db.query(User).filter_by(email="user@seatlock.com").first()
        if not test_user:
            test_user = User(
                email="user@seatlock.com",
                password_hash=hash_password("user123"),
                role="user"
            )
            db.add(test_user)

        db.flush()

        # 2. Seed Movies (3 movies)
        movies_data = [
            {
                "title": "Inception",
                "description": "A thief who steals corporate secrets through the use of dream-sharing technology is given the inverse task of planting an idea into the mind of a C.E.O.",
                "duration_minutes": 148,
                "poster_url": "https://images.unsplash.com/photo-1536440136628-849c177e76a1?w=800&auto=format&fit=crop"
            },
            {
                "title": "Interstellar",
                "description": "When Earth becomes uninhabitable in the future, a farmer and ex-NASA pilot, Joseph Cooper, is tasked to pilot a spacecraft, along with a team of researchers, to find a new planet for humans.",
                "duration_minutes": 169,
                "poster_url": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=800&auto=format&fit=crop"
            },
            {
                "title": "The Dark Knight",
                "description": "When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests of his ability to fight injustice.",
                "duration_minutes": 152,
                "poster_url": "https://images.unsplash.com/photo-1509198397868-475647b2a1e5?w=800&auto=format&fit=crop"
            }
        ]

        seeded_movies = []
        for m_data in movies_data:
            movie = db.query(Movie).filter_by(title=m_data["title"]).first()
            if not movie:
                movie = Movie(**m_data)
                db.add(movie)
                db.flush()
            seeded_movies.append(movie)

        # 3. Seed Shows (5 shows)
        now = datetime.now(timezone.utc)
        shows_data = [
            {
                "movie_id": seeded_movies[0].id,
                "screen_name": "Screen 1 (IMAX Laser)",
                "start_time": now + timedelta(hours=2),
                "price": 350.0
            },
            {
                "movie_id": seeded_movies[0].id,
                "screen_name": "Screen 2 (Dolby Cinema)",
                "start_time": now + timedelta(hours=6),
                "price": 280.0
            },
            {
                "movie_id": seeded_movies[1].id,
                "screen_name": "Screen 1 (IMAX Laser)",
                "start_time": now + timedelta(hours=10),
                "price": 400.0
            },
            {
                "movie_id": seeded_movies[2].id,
                "screen_name": "Screen 3 (4DX Atmos)",
                "start_time": now + timedelta(days=1, hours=3),
                "price": 320.0
            },
            {
                "movie_id": seeded_movies[2].id,
                "screen_name": "Screen 1 (IMAX Laser)",
                "start_time": now + timedelta(days=1, hours=7),
                "price": 350.0
            }
        ]

        # 4. Seed 10x10 Seats per show (A1 to J10 = 100 seats per show)
        row_labels = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
        col_numbers = list(range(1, 11))

        for s_data in shows_data:
            show = db.query(Show).filter_by(
                movie_id=s_data["movie_id"],
                screen_name=s_data["screen_name"]
            ).first()

            if not show:
                show = Show(**s_data)
                db.add(show)
                db.flush()

                seats = []
                for row in row_labels:
                    for col in col_numbers:
                        seat_label = f"{row}{col}"
                        seats.append(ShowSeat(
                            show_id=show.id,
                            seat_label=seat_label,
                            status="AVAILABLE",
                            locked_by=None,
                            locked_until=None
                        ))
                db.bulk_save_objects(seats)

        db.commit()
        print("[+] Database successfully seeded with 3 movies, 5 shows, and 10x10 (100) seats per show!")
    except Exception as e:
        db.rollback()
        print(f"[-] Error seeding database: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    seed()

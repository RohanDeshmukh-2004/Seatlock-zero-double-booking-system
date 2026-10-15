from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.db import engine, Base
import backend.app.models  # ensure models are imported for metadata

# Initialize database schema
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="SeatLock API",
    description="BookMyShow-style seat booking system with row-level locking concurrency control",
    version="1.0.0"
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.app.routes.auth import router as auth_router
from backend.app.routes.browse import router as browse_router
from backend.app.routes.locks import router as locks_router
from backend.app.routes.bookings import router as bookings_router

app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(browse_router, tags=["browse"])
app.include_router(locks_router, tags=["locks"])
app.include_router(bookings_router, prefix="/bookings", tags=["bookings"])

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "SeatLock",
        "version": "1.0.0",
        "message": "SeatLock backend base is operational"
    }

# Serve built frontend if available
import os
from fastapi.staticfiles import StaticFiles

frontend_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/dist"))
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")


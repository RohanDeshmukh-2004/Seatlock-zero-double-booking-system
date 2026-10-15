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

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": "SeatLock",
        "version": "1.0.0",
        "message": "SeatLock backend base is operational"
    }

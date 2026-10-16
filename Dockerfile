# ==========================================
# Stage 1: Build the React frontend
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# ==========================================
# Stage 2: Python FastAPI backend
# ==========================================
FROM python:3.13-slim

WORKDIR /app

# Install backend dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copy backend code
COPY backend/ ./backend/

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Expose default port
EXPOSE 8000

ENV PORT=8000
ENV PYTHONUNBUFFERED=1

# Seed the database and start the server on $PORT
CMD ["sh", "-c", "python -m backend.app.seed && uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

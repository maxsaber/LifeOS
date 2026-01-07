"""
LifeOS - Personal RAG System for Obsidian Vault
FastAPI Application Entry Point
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from api.routes import search, ask, calendar, gmail, drive

app = FastAPI(
    title="LifeOS",
    description="Personal assistant system for semantic search and synthesis across Obsidian vault",
    version="0.2.0"
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(search.router)
app.include_router(ask.router)
app.include_router(calendar.router)
app.include_router(gmail.router)
app.include_router(drive.router)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Convert validation errors to 400 with clear messages."""
    errors = exc.errors()

    # Sanitize errors for JSON serialization (convert bytes to string)
    sanitized_errors = []
    for error in errors:
        sanitized = dict(error)
        if "input" in sanitized and isinstance(sanitized["input"], bytes):
            sanitized["input"] = sanitized["input"].decode("utf-8", errors="replace")
        sanitized_errors.append(sanitized)

    # Check if this is an empty query error
    for error in errors:
        if "query" in str(error.get("loc", [])):
            return JSONResponse(
                status_code=400,
                content={"error": "Query cannot be empty", "detail": sanitized_errors}
            )
    return JSONResponse(
        status_code=400,
        content={"error": "Validation error", "detail": sanitized_errors}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "lifeos"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "LifeOS API", "version": "0.1.0"}

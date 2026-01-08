"""
LifeOS - Personal RAG System for Obsidian Vault
FastAPI Application Entry Point
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api.routes import search, ask, calendar, gmail, drive, people, chat, briefings, admin, conversations

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
app.include_router(people.router)
app.include_router(chat.router)
app.include_router(briefings.router)
app.include_router(admin.router)
app.include_router(conversations.router)

# Serve static files
web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")


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
    """Health check endpoint that verifies critical dependencies."""
    from config.settings import settings

    checks = {
        "api_key_configured": bool(settings.anthropic_api_key and settings.anthropic_api_key.strip()),
    }

    all_healthy = all(checks.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "service": "lifeos",
        "checks": checks,
    }


@app.get("/")
async def root():
    """Serve the chat UI."""
    index_path = Path(__file__).parent.parent / "web" / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "LifeOS API", "version": "0.3.0"}

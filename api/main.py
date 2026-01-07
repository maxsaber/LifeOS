"""
LifeOS - Personal RAG System for Obsidian Vault
FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="LifeOS",
    description="Personal assistant system for semantic search and synthesis across Obsidian vault",
    version="0.1.0"
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "lifeos"}


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "LifeOS API", "version": "0.1.0"}

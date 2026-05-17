"""Liveness + root endpoints. No business logic — these exist so a load
balancer / uptime probe can hit a stable URL without auth."""

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/")
async def root():
    return {"message": "Agentic Demo API is running"}


@router.get("/health")
async def health_check():
    return {"status": "healthy"}

import redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import router as auth_router
from api.config.config import FRONTEND_ORIGIN
from api.invoice.router import router as invoice_router

api = FastAPI(title="Notinha API")
api.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
api.include_router(auth_router)
api.include_router(invoice_router)


@api.exception_handler(redis.exceptions.ConnectionError)
async def redis_unavailable(request: Request, exc: redis.exceptions.ConnectionError):
    """One handler for every route that touches Redis."""
    return JSONResponse({"detail": "Serviço indisponível"}, status_code=503)

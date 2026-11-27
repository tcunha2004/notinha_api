import psycopg
import redis
import redis.exceptions
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import router as auth_router
from api.config.config import FRONTEND_ORIGIN
from api.invoice.router import router as invoice_router
from api.products.router import router as products_router
from api.purchases.router import router as purchases_router

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
api.include_router(purchases_router)
api.include_router(products_router)


@api.exception_handler(redis.exceptions.ConnectionError)
@api.exception_handler(redis.exceptions.TimeoutError)  # not a ConnectionError subclass
@api.exception_handler(psycopg.OperationalError)  # Postgres down or unreachable
async def service_unavailable(request: Request, exc: Exception):
    """One handler for every route that touches Redis or Postgres."""
    return JSONResponse({"detail": "Unavailable service"}, status_code=503)

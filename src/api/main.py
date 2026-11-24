from fastapi import FastAPI

from api.auth import router as auth_router
from api.invoice.router import router as invoice_router

api = FastAPI(title="Notinha API")
api.include_router(auth_router)
api.include_router(invoice_router)

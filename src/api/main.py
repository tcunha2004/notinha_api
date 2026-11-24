from fastapi import FastAPI

from api.invoice.router import router as invoice_router

api = FastAPI(title="Notinha API")
api.include_router(invoice_router)

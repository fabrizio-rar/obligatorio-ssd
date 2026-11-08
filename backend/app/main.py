from fastapi import FastAPI

from app.api import health

app = FastAPI(title="MercaNova API")
app.include_router(health.router, prefix="/api")

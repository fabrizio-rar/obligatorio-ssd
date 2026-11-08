from fastapi import FastAPI

from app.api import chat, health

app = FastAPI(title="MercaNova API")
app.include_router(health.router, prefix="/api")
app.include_router(chat.router, prefix="/api")

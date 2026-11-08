from fastapi import FastAPI

from app.api import auth, cart, catalog, chat, conversations, health, transcribe
from app.api.errors import register_error_handlers

app = FastAPI(title="MercaNova API")
register_error_handlers(app)
for module in (health, auth, catalog, cart, chat, conversations, transcribe):
    app.include_router(module.router, prefix="/api")

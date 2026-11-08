from fastapi import FastAPI

from app.api import auth, catalog, chat, health
from app.api.errors import register_error_handlers

app = FastAPI(title="MercaNova API")
register_error_handlers(app)
for module in (health, auth, catalog, chat):
    app.include_router(module.router, prefix="/api")

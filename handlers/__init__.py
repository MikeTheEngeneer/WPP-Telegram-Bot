"""Handlers package."""
from .start import router as start_router
from .connections import router as conns_router
from .clients import router as clients_router
from .subscriptions import router as subs_router
from .create import router as create_router
from .backup import router as backup_router

all_routers = [
    start_router,
    conns_router,
    clients_router,
    subs_router,
    create_router,
    backup_router,
]

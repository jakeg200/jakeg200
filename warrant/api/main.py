from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from warrant.api.routes import router
from warrant.db import create_all, session_scope
from warrant.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    create_all()
    with session_scope() as session:
        seed(session)
    yield


app = FastAPI(
    title="warrant",
    version="0.1.0",
    description=(
        "Assessment of derivations rather than answers. A claim is only as good as the "
        "warrant behind it."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

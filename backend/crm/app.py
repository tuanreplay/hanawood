from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api import router
from .database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Hanawood CRM", lifespan=lifespan)
app.include_router(router)

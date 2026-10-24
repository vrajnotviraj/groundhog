"""The console's HTTP server: the JSON API under /api and the built web app at /."""

from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from groundhog import config, db
from groundhog.api import auth, cases, flows, runs, settings

WEB_DIST = config.ROOT / "web" / "dist"


class SinglePageApp(StaticFiles):
    """Static files, with index.html for any path that is not a file, so client routes load."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.ensure_indexes()
    yield


app = FastAPI(title="groundhog", lifespan=lifespan)
app.middleware("http")(auth.reject_foreign_origin)
for module in (auth, cases, flows, runs, settings):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    mongo = db.ping()
    return {"ok": mongo, "mongo": mongo, "version": version("groundhog")}


if WEB_DIST.is_dir():
    app.mount("/", SinglePageApp(directory=WEB_DIST, html=True), name="web")

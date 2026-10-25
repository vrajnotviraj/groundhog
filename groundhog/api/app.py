"""The console's HTTP server: the JSON API under /api and the built web app at /."""

from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from groundhog import config, db
from groundhog.api import auth, cases, flows, jobs, map, runs, settings, suggestions

WEB_DIST = config.ROOT / "web" / "dist"


class SinglePageApp(StaticFiles):
    """Serve static files, and index.html for any other path outside /api."""

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
    jobs.close_orphaned_runs()
    yield


app = FastAPI(title="groundhog", lifespan=lifespan)
app.middleware("http")(auth.reject_foreign_origin)
for module in (auth, cases, flows, map, runs, settings, suggestions):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health")
def health() -> dict:
    return {"mongo": db.ping(), "version": version("groundhog")}


if WEB_DIST.is_dir():
    app.mount("/", SinglePageApp(directory=WEB_DIST, html=True), name="web")

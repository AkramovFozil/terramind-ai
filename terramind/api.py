"""Run with: python -m uvicorn terramind.api:app --host 127.0.0.1 --port 8000."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from terramind.search_service import SearchBusyError, SearchService, TerrainNotReadyError


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=25, ge=25, le=25)


def create_app(service: SearchService | None = None, serve_frontend: bool = True) -> FastAPI:
    backend = service or SearchService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        backend.close()

    app = FastAPI(title="TerraMind DEM Search", version="0.2.0", lifespan=lifespan)
    app.state.search_service = backend
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?", allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Do not echo non-finite JSON values back into a JSON response.
        return JSONResponse(status_code=422, content={"detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

    @app.get("/api/health")
    def health():
        return {"status": "ok", "service": "TerraMind DEM Search", "synthetic_fallback": False}

    @app.get("/api/catalog")
    def catalog():
        return backend.catalog()

    @app.post("/api/search", status_code=202)
    def search(request: SearchRequest):
        try:
            return backend.submit(request.lat, request.lon, request.radius_km)
        except SearchBusyError as exc:
            raise HTTPException(status_code=503, detail=str(exc), headers={"Retry-After": "5"}) from None

    @app.get("/api/search/{job_id}")
    def status(job_id: str):
        try:
            return backend.get_job(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Search job not found or expired") from None

    @app.get("/api/terrain")
    def terrain(job_id: str = Query(min_length=1), site_id: str = Query(default="target", min_length=1)):
        try:
            return backend.get_terrain(job_id, site_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Search job not found or expired") from None
        except TerrainNotReadyError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    frontend = Path(os.environ.get("TERRAMIND_WEB_DIST", str(Path(__file__).resolve().parents[1] / "web" / "dist")))
    if serve_frontend and (frontend / "index.html").exists():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()

import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import __version__
from .api import applications, auth, candidates, comms, jobs, system, voice
from .api.deps import current_user
from .config import get_settings
from .db import SessionLocal, init_db
from .logging_setup import configure_logging

configure_logging()
log = logging.getLogger("talentflow.http")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_migrate:
        init_db()
    with SessionLocal() as db:
        auth.ensure_bootstrap_admin(db)
    embedded = None
    if settings.run_embedded_worker:
        from .worker import start_embedded

        embedded = start_embedded()
    yield
    if embedded:
        embedded[1].set()
        embedded[0].join(timeout=30)


app = FastAPI(
    title="TalentFlow API",
    description="Multi-agent recruiting pipeline powered by Claude",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )
app.add_middleware(GZipMiddleware, minimum_size=1024)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("Unhandled error", extra={"request_id": request_id, "path": request.url.path})
        response = JSONResponse({"detail": "Internal server error", "request_id": request_id}, status_code=500)
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    response.headers["X-Request-ID"] = request_id
    if request.url.path.startswith("/api/") and request.url.path not in ("/api/health", "/api/ready"):
        log.info(
            "%s %s %s", request.method, request.url.path, response.status_code,
            extra={
                "request_id": request_id, "method": request.method, "path": request.url.path,
                "status": response.status_code, "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "user_id": getattr(request.state, "user_id", None),
            },
        )
    return response


# Public: health checks and sign-in. Everything else requires a session.
app.include_router(system.public_router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(voice.router, prefix="/api")  # Twilio: signature- and token-authenticated
for module in (system, jobs, candidates, applications, comms):
    app.include_router(module.router, prefix="/api", dependencies=[Depends(current_user)])

# Serve the built frontend when it is present (single-container deployments).
_static = Path(__file__).resolve().parent.parent / "static"
if _static.is_dir():

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        file = (_static / path).resolve()
        if path and file.is_file() and file.is_relative_to(_static.resolve()):
            # Vite fingerprints asset names, so they can be cached forever.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(file, headers={"Cache-Control": cache})
        return FileResponse(_static / "index.html", headers={"Cache-Control": "no-cache"})

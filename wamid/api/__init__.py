"""Optional FastAPI surface over the same services the CLI uses.
Install with: uv sync --extra server"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .. import config as config_mod
from . import digests, journals, projects, records, repos

app = FastAPI(title="wamid", version="0.1.0")

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def write_guard(request: Request, call_next):
    """Gatekeep writes. Read-only mode wins outright. Otherwise, if a write
    token is configured, require `Authorization: Bearer <token>` on non-safe
    methods. Config is read per-request so toggling doesn't need a restart."""
    if request.method in _SAFE_METHODS:
        return await call_next(request)
    api_cfg = config_mod.load().api
    if api_cfg.read_only:
        return JSONResponse({"detail": "api is in read-only mode"}, status_code=403)
    if api_cfg.write_token:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token != api_cfg.write_token:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health() -> dict:
    api_cfg = config_mod.load().api
    return {
        "ok": True,
        "read_only": api_cfg.read_only,
        "auth_required": bool(api_cfg.write_token),
    }


app.include_router(projects.router)
app.include_router(repos.router)
app.include_router(journals.router)
app.include_router(records.router)
app.include_router(digests.router)

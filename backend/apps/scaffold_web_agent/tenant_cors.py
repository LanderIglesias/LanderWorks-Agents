from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .tenants import resolve_tenant_by_token


class ScaffoldTenantCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Only apply tenant CORS validation to scaffold chat endpoint.
        # Admin, demo, widget.js and health must remain accessible without tenant token.
        if path != "/scaffold-agent/chat":
            return await call_next(request)

        origin = request.headers.get("origin", "")
        if not origin:
            return await call_next(request)

        # Token can come from header (normal requests) or query param (preflight)
        token = request.headers.get("x-widget-token", "") or request.query_params.get("token", "")
        tenant = resolve_tenant_by_token(token) if token else None

        if not tenant:
            return Response(status_code=401, content="Invalid or missing tenant token")

        allowed = set(tenant.allowed_origins or [])
        if origin not in allowed:
            return Response(status_code=403, content="Origin not allowed")

        # Explicitly intercept browser preflight before FastAPI sees it
        if request.method.upper() == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type,X-Widget-Token"
        response.headers["Access-Control-Max-Age"] = "86400"
        return response

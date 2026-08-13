#!/usr/bin/env python3
"""
Trivena Office Auth — device-code login compatible with TrivOffice desktop.

Implements the same contract GenOffice/TrivOffice used against Genspark:
  POST /api/office_addin_auth/device_code?app_type=…
  GET  /office-auth/verify?code=…          (browser approve UI)
  GET  /api/office_addin_auth/token?code=…
  POST /api/office_addin_auth/session
  POST /api/api_tokens/create
  POST /api/api_tokens/revoke

User identity is the logged-in Trivena Cloud (Frappe Press) session cookie
validated against FRAPPE_BASE_URL (default https://cloud.trivena.tech).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("OFFICE_AUTH_DATA", "/var/lib/trivena-office-auth"))
DB_PATH = DATA_DIR / "office_auth.db"
FRAPPE_BASE = os.environ.get("FRAPPE_BASE_URL", "https://cloud.trivena.tech").rstrip("/")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE_URL", FRAPPE_BASE).rstrip("/")
DEVICE_TTL_SEC = int(os.environ.get("DEVICE_TTL_SEC", "600"))
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL_SEC", "2"))
ACCESS_TTL_SEC = int(os.environ.get("ACCESS_TTL_SEC", "2592000"))  # 30 days
SESSION_COOKIE = "trivoffice_session"
SESSION_TTL_SEC = 60 * 60 * 12

app = FastAPI(title="Trivena Office Auth", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def _now() -> int:
    return int(time.time())


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS device_codes (
              code TEXT PRIMARY KEY,
              app_type TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              user_email TEXT,
              access_token_hash TEXT,
              access_token_plain TEXT,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              approved_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              user_email TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_keys (
              key_id TEXT PRIMARY KEY,
              key_hash TEXT NOT NULL UNIQUE,
              key_prefix TEXT NOT NULL,
              user_email TEXT NOT NULL,
              key_name TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              revoked_at INTEGER
            );
            """
        )


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def json_ok(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status)


def json_err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"message": message, "status": "error"}, status_code=status)


async def frappe_logged_in_email(request: Request) -> str | None:
    """Return the Press/Frappe user email if the browser has a valid sid cookie."""
    sid = request.cookies.get("sid")
    if not sid or sid == "Guest":
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=True) as client:
            resp = await client.get(
                f"{FRAPPE_BASE}/api/method/frappe.auth.get_logged_user",
                cookies={"sid": sid},
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        email = data.get("message")
        if isinstance(email, str) and email and email != "Guest":
            return email
    except Exception:
        return None
    return None


@app.post("/api/office_addin_auth/device_code")
async def device_code(app_type: str = "trivoffice") -> JSONResponse:
    code = secrets.token_urlsafe(24)
    created = _now()
    expires = created + DEVICE_TTL_SEC
    with db() as conn:
        conn.execute(
            "INSERT INTO device_codes (code, app_type, status, created_at, expires_at) VALUES (?,?,?,?,?)",
            (code, app_type or "trivoffice", "pending", created, expires),
        )
    auth_url = f"{PUBLIC_BASE}/office-auth/verify?code={quote(code)}"
    return json_ok(
        {
            "device_code": code,
            "auth_url": auth_url,
            "expires_in": DEVICE_TTL_SEC,
            "poll_interval": POLL_INTERVAL_SEC,
        }
    )


@app.get("/api/office_addin_auth/token")
async def token(code: str) -> JSONResponse:
    with db() as conn:
        row = conn.execute("SELECT * FROM device_codes WHERE code = ?", (code,)).fetchone()
    if not row:
        return json_ok({"status": "expired"})
    if row["expires_at"] < _now() and row["status"] == "pending":
        with db() as conn:
            conn.execute("UPDATE device_codes SET status = 'expired' WHERE code = ?", (code,))
        return json_ok({"status": "expired"})
    if row["status"] == "pending":
        return json_ok({"status": "pending"})
    if row["status"] == "approved":
        return json_ok(
            {
                "status": "approved",
                "access_token": row["access_token_plain"] or "",
            }
        )
    return json_ok({"status": "expired"})


@app.post("/api/office_addin_auth/session")
async def session(request: Request) -> Response:
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return json_err("missing bearer", 401)
    access = auth.split(" ", 1)[1].strip()
    if not access:
        return json_err("missing bearer", 401)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM device_codes WHERE access_token_hash = ? AND status = 'approved'",
            (_hash(access),),
        ).fetchone()
    if not row or not row["user_email"]:
        return json_err("invalid token", 401)
    session_token = secrets.token_urlsafe(32)
    created = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_email, created_at, expires_at) VALUES (?,?,?,?)",
            (_hash(session_token), row["user_email"], created, created + SESSION_TTL_SEC),
        )
    resp = json_ok({"ok": True, "email": row["user_email"]})
    resp.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_TTL_SEC,
        path="/",
    )
    return resp


def _session_email(request: Request) -> str | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?",
            (_hash(raw),),
        ).fetchone()
    if not row or row["expires_at"] < _now():
        return None
    return row["user_email"]


@app.post("/api/api_tokens/create")
async def create_api_token(request: Request) -> JSONResponse:
    email = _session_email(request)
    if not email:
        return json_err("not authenticated", 401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key_name = str(body.get("key_name") or "trivoffice")
    key_id = secrets.token_hex(8)
    token = f"trk-{secrets.token_urlsafe(32)}"
    created = _now()
    with db() as conn:
        conn.execute(
            "INSERT INTO api_keys (key_id, key_hash, key_prefix, user_email, key_name, created_at) VALUES (?,?,?,?,?,?)",
            (key_id, _hash(token), token[:10], email, key_name, created),
        )
    return json_ok({"message": "ok", "data": {"token": token, "key_id": key_id, "key_name": key_name}})


@app.post("/api/api_tokens/revoke")
async def revoke_api_token(request: Request) -> JSONResponse:
    email = _session_email(request)
    if not email:
        return json_err("not authenticated", 401)
    try:
        body = await request.json()
    except Exception:
        body = {}
    key_id = str(body.get("key_id") or "")
    if not key_id:
        return json_err("key_id required")
    with db() as conn:
        conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE key_id = ? AND user_email = ?",
            (_now(), key_id, email),
        )
    return json_ok({"message": "ok"})


@app.get("/office-auth/verify", response_class=HTMLResponse)
async def verify_page(request: Request, code: str = "") -> Response:
    if not code:
        return HTMLResponse("<h1>Missing code</h1>", status_code=400)
    with db() as conn:
        row = conn.execute("SELECT * FROM device_codes WHERE code = ?", (code,)).fetchone()
    if not row:
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "error": "This sign-in link is invalid.", "code": code, "email": None},
            status_code=400,
        )
    if row["expires_at"] < _now() and row["status"] == "pending":
        return templates.TemplateResponse(
            "verify.html",
            {"request": request, "error": "This sign-in link has expired. Return to TrivOffice and try again.", "code": code, "email": None},
            status_code=400,
        )
    if row["status"] == "approved":
        return templates.TemplateResponse(
            "verify.html",
            {
                "request": request,
                "done": True,
                "code": code,
                "email": row["user_email"],
                "error": None,
            },
        )

    email = await frappe_logged_in_email(request)
    if not email:
        redirect_to = quote(f"/office-auth/verify?code={code}", safe="")
        return RedirectResponse(f"{FRAPPE_BASE}/login?redirect-to={redirect_to}", status_code=302)

    return templates.TemplateResponse(
        "verify.html",
        {
            "request": request,
            "code": code,
            "email": email,
            "error": None,
            "done": False,
            "app_name": "TrivOffice",
        },
    )


@app.post("/office-auth/verify")
async def verify_approve(request: Request) -> Response:
    form = await request.form()
    code = str(form.get("code") or "")
    action = str(form.get("action") or "approve")
    email = await frappe_logged_in_email(request)
    if not email:
        redirect_to = quote(f"/office-auth/verify?code={code}", safe="")
        return RedirectResponse(f"{FRAPPE_BASE}/login?redirect-to={redirect_to}", status_code=302)
    with db() as conn:
        row = conn.execute("SELECT * FROM device_codes WHERE code = ?", (code,)).fetchone()
        if not row or row["expires_at"] < _now():
            return templates.TemplateResponse(
                "verify.html",
                {"request": request, "error": "This sign-in link has expired.", "code": code, "email": email},
                status_code=400,
            )
        if action == "deny":
            conn.execute("UPDATE device_codes SET status = 'expired' WHERE code = ?", (code,))
            return templates.TemplateResponse(
                "verify.html",
                {
                    "request": request,
                    "error": "Sign-in denied. You can close this window.",
                    "code": code,
                    "email": email,
                    "done": False,
                },
            )
        access = secrets.token_urlsafe(32)
        conn.execute(
            """UPDATE device_codes
               SET status = 'approved', user_email = ?, access_token_hash = ?,
                   access_token_plain = ?, approved_at = ?
               WHERE code = ? AND status = 'pending'""",
            (email, _hash(access), access, _now(), code),
        )
    return RedirectResponse(f"/office-auth/verify?code={quote(code)}", status_code=302)


@app.get("/api/office-auth/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "trivena-office-auth"}


# --- API key lookup helper for future LLM gateway ---
def lookup_api_key(token: str) -> str | None:
    with db() as conn:
        row = conn.execute(
            "SELECT user_email FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (_hash(token),),
        ).fetchone()
    return row["user_email"] if row else None


# ── Minimal LLM gateway (Phase 2 starter) ─────────────────────────────
# Validates TrivOffice API keys and proxies to vendor APIs when keys are
# present in the service environment (ANTHROPIC_API_KEY / OPENAI_API_KEY).


def _require_office_key(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in to Trivena Cloud from TrivOffice")
    token = authorization.split(" ", 1)[1].strip()
    email = lookup_api_key(token)
    if not email:
        # Also accept the raw token stored during login when hash lookup fails
        # for legacy keys — primary path is hashed lookup above.
        raise HTTPException(status_code=401, detail="Invalid TrivOffice API key")
    return email


@app.api_route("/api/llm/anthropic/{path:path}", methods=["GET", "POST"])
async def llm_anthropic(path: str, request: Request, authorization: str | None = Header(default=None)):
    _require_office_key(authorization)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return JSONResponse(
            {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": "Trivena Cloud LLM gateway is signed-in ready, but ANTHROPIC_API_KEY is not configured on the server yet.",
                },
            },
            status_code=503,
        )
    body = await request.body()
    headers = {
        "x-api-key": api_key,
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }
    url = f"https://api.anthropic.com/{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(request.method, url, content=body, headers=headers)
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))


@app.api_route("/api/llm/openai/v1/{path:path}", methods=["GET", "POST"])
async def llm_openai(path: str, request: Request, authorization: str | None = Header(default=None)):
    """Proxy OpenAI-compatible traffic to OpenRouter (primary TrivOffice path)."""
    email = _require_office_key(authorization)
    api_key = os.environ.get("OPENROUTER_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return JSONResponse(
            {
                "error": {
                    "message": "OPENROUTER_API_KEY is not configured on the Trivena Cloud gateway.",
                    "type": "server_error",
                }
            },
            status_code=503,
        )
    body = await request.body()
    # Free-tier OpenRouter balances reject high max_tokens (HTTP 402). Clamp so
    # desktop clients keep working even when they still send 8192.
    max_tokens_cap = int(os.environ.get("OPENROUTER_MAX_TOKENS", "2048"))
    if request.method.upper() == "POST" and body:
        try:
            payload = json.loads(body)
            if isinstance(payload, dict):
                requested = payload.get("max_tokens")
                if isinstance(requested, (int, float)) and requested > max_tokens_cap:
                    payload["max_tokens"] = max_tokens_cap
                    body = json.dumps(payload).encode("utf-8")
                elif requested is None and max_tokens_cap > 0:
                    payload["max_tokens"] = max_tokens_cap
                    body = json.dumps(payload).encode("utf-8")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": request.headers.get("content-type", "application/json"),
        "HTTP-Referer": os.environ.get("PUBLIC_BASE_URL", "https://cloud.trivena.tech"),
        "X-Title": "TrivOffice",
        "X-Trivena-User": email,
    }
    # OpenRouter is OpenAI-compatible at /api/v1/*
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    url = f"{base}/{path}"
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
    req = client.build_request(request.method, url, content=body, headers=headers)
    upstream = await client.send(req, stream=True)

    async def relay():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
    )


@app.api_route("/api/llm/gemini/v1beta/{path:path}", methods=["GET", "POST"])
async def llm_gemini(path: str, request: Request, authorization: str | None = Header(default=None)):
    _require_office_key(authorization)
    api_key = os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        return JSONResponse(
            {"error": {"message": "GEMINI_API_KEY not configured on Trivena Cloud gateway.", "status": "UNAVAILABLE"}},
            status_code=503,
        )
    body = await request.body()
    sep = "&" if "?" in path else "?"
    url = f"https://generativelanguage.googleapis.com/v1beta/{path}{sep}key={api_key}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(request.method, url, content=body, headers={"content-type": "application/json"})
    return Response(content=upstream.content, status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))

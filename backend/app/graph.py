from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import json
import os
import random
import secrets
import subprocess

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from .config import get_settings
from .db import connect
from .proxies import set_proxy_status, validate_proxy_connect

router = APIRouter(prefix="/api", tags=["microsoft-graph"])

AUTHORITY = "https://login.microsoftonline.com/consumers"
AUTH_URL = f"{AUTHORITY}/oauth2/v2.0/authorize"
TOKEN_URL = f"{AUTHORITY}/oauth2/v2.0/token"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.Read"


def require_ms_config():
    settings = get_settings()
    if not settings.microsoft_client_id:
        raise HTTPException(
            status_code=400,
            detail="Missing MS_CLIENT_ID. Configure backend/.env first.",
        )
    return settings


def build_oauth_url(account_id: int) -> str:
    settings = require_ms_config()
    with connect() as conn:
        account = conn.execute(
            "SELECT id FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        state = f"{account_id}:{secrets.token_urlsafe(24)}"
        conn.execute(
            "UPDATE accounts SET status = ?, last_error = NULL WHERE id = ?",
            ("authorizing", account_id),
        )

    params = urlencode(
        {
            "client_id": settings.microsoft_client_id,
            "response_type": "code",
            "redirect_uri": settings.microsoft_redirect_uri,
            "response_mode": "query",
            "scope": SCOPES,
            "state": state,
            "prompt": "select_account",
        }
    )
    return f"{AUTH_URL}?{params}"


@router.get("/oauth/microsoft/start/{account_id}")
def start_oauth(account_id: int):
    return {"url": build_oauth_url(account_id)}


@router.post("/oauth/microsoft/playwright/{account_id}")
def start_playwright_oauth(account_id: int):
    auth_url = build_oauth_url(account_id)
    selected_proxy = pick_playwright_proxy(require_valid=True)
    root_dir = Path(__file__).resolve().parents[2]
    frontend_dir = root_dir / "frontend"
    script_path = frontend_dir / "scripts" / "open-auth-browser.mjs"
    profile_dir = root_dir / "backend" / "data" / "playwright-profiles" / f"account-{account_id}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    if not script_path.exists():
        raise HTTPException(status_code=500, detail="Playwright launcher script not found")

    popen_kwargs = {
        "cwd": str(frontend_dir),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        subprocess.Popen(
            [
                "node",
                str(script_path),
                auth_url,
                str(profile_dir),
                json.dumps(selected_proxy or {}),
            ],
            **popen_kwargs,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Node.js not found in PATH") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to launch Playwright: {exc}") from exc

    return {
        "started": True,
        "mode": "playwright_manual",
        "account_id": account_id,
        "proxy": sanitize_proxy(selected_proxy),
    }


def pick_playwright_proxy(require_valid: bool = False) -> dict[str, str] | None:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, type, host, port, username, password
            FROM proxies
            WHERE status = 'active'
            """
        ).fetchall()

    if not rows:
        return None

    candidates = [dict(row) for row in rows]
    random.shuffle(candidates)
    saw_proxy = False

    for proxy in candidates:
        saw_proxy = True
        if require_valid:
            ok, _ = validate_proxy_connect(proxy)
            if not ok:
                set_proxy_status(proxy["id"], "invalid")
                continue
            set_proxy_status(proxy["id"], "active")
        return build_playwright_proxy(proxy)

    if saw_proxy and require_valid:
        raise HTTPException(
            status_code=400,
            detail="No valid active proxy is available. Import or validate proxies first.",
        )

    return None


def build_playwright_proxy(proxy: dict) -> dict[str, str]:
    server = f"{proxy['type']}://{proxy['host']}:{proxy['port']}"
    result = {"server": server}
    if proxy.get("username"):
        result["username"] = proxy["username"]
    if proxy.get("password"):
        result["password"] = proxy["password"]
    return result


def sanitize_proxy(proxy: dict[str, str] | None) -> dict[str, str] | None:
    if not proxy:
        return None
    safe = {"server": proxy["server"]}
    if proxy.get("username"):
        safe["username"] = proxy["username"]
    return safe


@router.get("/oauth/microsoft/callback")
async def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    settings = require_ms_config()
    if error:
        return RedirectResponse(f"{settings.app_base_url}/?oauth=failed&error={error}")
    if not code or not state or ":" not in state:
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")

    account_id = int(state.split(":", 1)[0])
    data = {
        "client_id": settings.microsoft_client_id,
        "scope": SCOPES,
        "code": code,
        "redirect_uri": settings.microsoft_redirect_uri,
        "grant_type": "authorization_code",
    }
    if settings.microsoft_client_secret:
        data["client_secret"] = settings.microsoft_client_secret

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data=data)
    if response.status_code >= 400:
        with connect() as conn:
            conn.execute(
                "UPDATE accounts SET status = ?, last_error = ? WHERE id = ?",
                ("auth_failed", response.text[:500], account_id),
            )
        return RedirectResponse(f"{settings.app_base_url}/?oauth=failed")

    token = response.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.get("expires_in", 3600))
    with connect() as conn:
        conn.execute(
            """
            UPDATE accounts
            SET access_token = ?, refresh_token = ?, token_expires_at = ?,
                status = ?, last_error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                token.get("access_token"),
                token.get("refresh_token"),
                expires_at.isoformat(),
                "authorized",
                account_id,
            ),
        )
    return RedirectResponse(f"{settings.app_base_url}/?oauth=success")


async def refresh_access_token(account_id: int) -> str:
    settings = require_ms_config()
    with connect() as conn:
        account = conn.execute(
            "SELECT refresh_token FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
    if not account or not account["refresh_token"]:
        raise HTTPException(status_code=400, detail="Account is not authorized")

    data = {
        "client_id": settings.microsoft_client_id,
        "scope": SCOPES,
        "refresh_token": account["refresh_token"],
        "redirect_uri": settings.microsoft_redirect_uri,
        "grant_type": "refresh_token",
    }
    if settings.microsoft_client_secret:
        data["client_secret"] = settings.microsoft_client_secret

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(TOKEN_URL, data=data)
    if response.status_code >= 400:
        with connect() as conn:
            conn.execute(
                "UPDATE accounts SET status = ?, last_error = ? WHERE id = ?",
                ("auth_expired", response.text[:500], account_id),
            )
        raise HTTPException(status_code=401, detail="Token refresh failed")

    token = response.json()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.get("expires_in", 3600))
    refresh_token = token.get("refresh_token") or account["refresh_token"]
    with connect() as conn:
        conn.execute(
            """
            UPDATE accounts
            SET access_token = ?, refresh_token = ?, token_expires_at = ?,
                status = ?, last_error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (token["access_token"], refresh_token, expires_at.isoformat(), "authorized", account_id),
        )
    return token["access_token"]


@router.post("/sync/accounts/{account_id}")
async def sync_account(account_id: int):
    access_token = await refresh_access_token(account_id)
    headers = {"Authorization": f"Bearer {access_token}"}
    folders_url = f"{GRAPH_BASE}/me/mailFolders?$top=100"

    async with httpx.AsyncClient(timeout=30) as client:
        folders_resp = await client.get(folders_url, headers=headers)
        if folders_resp.status_code >= 400:
            raise HTTPException(status_code=folders_resp.status_code, detail=folders_resp.text)
        folders = folders_resp.json().get("value", [])

        stored_messages = 0
        with connect() as conn:
            for folder in folders:
                cursor = conn.execute(
                    """
                    INSERT INTO mail_folders (
                        account_id, provider_folder_id, display_name, well_known_name,
                        unread_count, total_count, synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(account_id, provider_folder_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        well_known_name = excluded.well_known_name,
                        unread_count = excluded.unread_count,
                        total_count = excluded.total_count,
                        synced_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        account_id,
                        folder["id"],
                        folder.get("displayName", ""),
                        folder.get("wellKnownName"),
                        folder.get("unreadItemCount", 0),
                        folder.get("totalItemCount", 0),
                    ),
                )
                local_folder_id = cursor.fetchone()["id"]
                msg_url = (
                    f"{GRAPH_BASE}/me/mailFolders/{folder['id']}/messages"
                    "?$top=25&$select=id,subject,from,bodyPreview,receivedDateTime,isRead"
                    "&$orderby=receivedDateTime desc"
                )
                msg_resp = await client.get(msg_url, headers=headers)
                if msg_resp.status_code >= 400:
                    continue
                for msg in msg_resp.json().get("value", []):
                    sender = (
                        msg.get("from", {})
                        .get("emailAddress", {})
                        .get("address")
                    )
                    conn.execute(
                        """
                        INSERT INTO messages (
                            account_id, folder_id, provider_message_id, sender,
                            subject, snippet, received_at, is_read, synced_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(account_id, provider_message_id) DO UPDATE SET
                            folder_id = excluded.folder_id,
                            sender = excluded.sender,
                            subject = excluded.subject,
                            snippet = excluded.snippet,
                            received_at = excluded.received_at,
                            is_read = excluded.is_read,
                            synced_at = CURRENT_TIMESTAMP
                        """,
                        (
                            account_id,
                            local_folder_id,
                            msg["id"],
                            sender,
                            msg.get("subject"),
                            msg.get("bodyPreview"),
                            msg.get("receivedDateTime"),
                            1 if msg.get("isRead") else 0,
                        ),
                    )
                    stored_messages += 1
            conn.execute(
                """
                UPDATE accounts
                SET last_sync_at = CURRENT_TIMESTAMP, status = ?, last_error = NULL
                WHERE id = ?
                """,
                ("authorized", account_id),
            )
            conn.execute(
                "INSERT INTO sync_logs (account_id, level, message) VALUES (?, ?, ?)",
                (account_id, "info", f"Synced {len(folders)} folders and {stored_messages} messages"),
            )

    return {"folders": len(folders), "messages": stored_messages}


@router.get("/accounts/{account_id}/folders")
def list_folders(account_id: int):
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, account_id, provider_folder_id, display_name, well_known_name,
                   unread_count, total_count, synced_at
            FROM mail_folders
            WHERE account_id = ?
            ORDER BY display_name
            """,
            (account_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/accounts/{account_id}/messages")
def list_messages(account_id: int, folder_id: int | None = None):
    params: list[int] = [account_id]
    where = "WHERE account_id = ?"
    if folder_id:
        where += " AND folder_id = ?"
        params.append(folder_id)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, account_id, folder_id, sender, subject, snippet, received_at, is_read
            FROM messages
            {where}
            ORDER BY received_at DESC
            LIMIT 200
            """,
            params,
        ).fetchall()
    return [{**dict(row), "is_read": bool(row["is_read"])} for row in rows]

import base64
import socket

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connect

router = APIRouter(prefix="/api/proxies", tags=["proxies"])
PROXY_TEST_HOST = "login.microsoftonline.com"
PROXY_TEST_PORT = 443
PROXY_TIMEOUT_SECONDS = 8


class ImportProxiesRequest(BaseModel):
    text: str = Field(min_length=1)
    type: str = "http"


def parse_proxy_lines(text: str, proxy_type: str) -> list[dict[str, str | int]]:
    proxies = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue

        parts = [part.strip() for part in raw.split(":")]
        if len(parts) not in (2, 4):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid proxy format: {raw}. Expected host:port or host:port:user:pass",
            )

        host = parts[0]
        try:
            port = int(parts[1])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid proxy port: {raw}") from exc

        username = parts[2] if len(parts) == 4 else ""
        password = parts[3] if len(parts) == 4 else ""
        proxies.append(
            {
                "name": f"{host}:{port}",
                "type": proxy_type,
                "host": host,
                "port": port,
                "username": username,
                "password": password,
            }
        )
    return proxies


@router.get("")
def list_proxies():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, type, host, port, username, status, created_at
            FROM proxies
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/import")
def import_proxies(payload: ImportProxiesRequest):
    proxy_type = payload.type.lower().strip()
    if proxy_type not in {"http", "https", "socks5"}:
        raise HTTPException(status_code=400, detail="Proxy type must be http, https, or socks5")

    parsed = parse_proxy_lines(payload.text, proxy_type)
    created = 0
    updated = 0

    with connect() as conn:
        for item in parsed:
            existing = conn.execute(
                "SELECT id FROM proxies WHERE host = ? AND port = ? AND username = ?",
                (item["host"], item["port"], item["username"]),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE proxies
                    SET name = ?, type = ?, password = ?, status = ?
                    WHERE id = ?
                    """,
                    (
                        item["name"],
                        item["type"],
                        item["password"],
                        "active",
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO proxies (name, type, host, port, username, password, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["name"],
                        item["type"],
                        item["host"],
                        item["port"],
                        item["username"],
                        item["password"],
                        "active",
                    ),
                )
                created += 1

    return {"parsed": len(parsed), "created": created, "updated": updated}


def validate_proxy_connect(proxy: dict) -> tuple[bool, str]:
    if proxy["type"] not in {"http", "https"}:
        return True, "Skipped validation for non-HTTP proxy"

    auth_header = ""
    if proxy.get("username"):
        raw_auth = f"{proxy['username']}:{proxy.get('password') or ''}".encode()
        token = base64.b64encode(raw_auth).decode()
        auth_header = f"Proxy-Authorization: Basic {token}\r\n"

    request = (
        f"CONNECT {PROXY_TEST_HOST}:{PROXY_TEST_PORT} HTTP/1.1\r\n"
        f"Host: {PROXY_TEST_HOST}:{PROXY_TEST_PORT}\r\n"
        f"{auth_header}"
        "Proxy-Connection: Keep-Alive\r\n"
        "\r\n"
    ).encode()

    try:
        with socket.create_connection(
            (proxy["host"], int(proxy["port"])),
            timeout=PROXY_TIMEOUT_SECONDS,
        ) as sock:
            sock.settimeout(PROXY_TIMEOUT_SECONDS)
            sock.sendall(request)
            response = sock.recv(512).decode("iso-8859-1", errors="replace")
    except OSError as exc:
        return False, str(exc)

    first_line = response.splitlines()[0] if response else "Empty proxy response"
    if " 200 " in first_line:
        return True, first_line
    return False, first_line


def set_proxy_status(proxy_id: int, status: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE proxies SET status = ? WHERE id = ?", (status, proxy_id))


@router.post("/{proxy_id}/validate")
def validate_proxy(proxy_id: int):
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id, type, host, port, username, password
            FROM proxies
            WHERE id = ?
            """,
            (proxy_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Proxy not found")

    ok, message = validate_proxy_connect(dict(row))
    set_proxy_status(proxy_id, "active" if ok else "invalid")
    return {"id": proxy_id, "ok": ok, "status": "active" if ok else "invalid", "message": message}


@router.post("/validate-active")
def validate_active_proxies():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, type, host, port, username, password
            FROM proxies
            WHERE status = 'active'
            ORDER BY id DESC
            """
        ).fetchall()

    checked = 0
    valid = 0
    invalid = 0
    for row in rows:
        checked += 1
        proxy = dict(row)
        ok, _ = validate_proxy_connect(proxy)
        set_proxy_status(proxy["id"], "active" if ok else "invalid")
        if ok:
            valid += 1
        else:
            invalid += 1

    return {"checked": checked, "valid": valid, "invalid": invalid}

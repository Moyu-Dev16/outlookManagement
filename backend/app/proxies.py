from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connect

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


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

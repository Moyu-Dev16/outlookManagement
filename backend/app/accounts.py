from fastapi import APIRouter, HTTPException

from .config import get_settings
from .db import connect
from .models import AccountOut, ImportAccountsRequest

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def parse_import_text(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = [part.strip() for part in raw.split("----")]
        if len(parts) < 1 or not parts[0]:
            continue
        rows.append(
            {
                "email": parts[0],
                "password": parts[1] if len(parts) > 1 else "",
                "totp_secret": parts[2] if len(parts) > 2 else "",
            }
        )
    return rows


@router.get("", response_model=list[AccountOut])
def list_accounts():
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, email, auth_mode, status, proxy_id, last_sync_at, last_error, created_at
            FROM accounts
            ORDER BY id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/import")
def import_accounts(payload: ImportAccountsRequest):
    parsed = parse_import_text(payload.text)
    created = 0
    updated = 0
    with connect() as conn:
        for item in parsed:
            existing = conn.execute(
                "SELECT id FROM accounts WHERE email = ?", (item["email"],)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE accounts
                    SET password = ?, totp_secret = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE email = ?
                    """,
                    (item["password"], item["totp_secret"], item["email"]),
                )
                updated += 1
            else:
                conn.execute(
                    """
                    INSERT INTO accounts (email, password, totp_secret)
                    VALUES (?, ?, ?)
                    """,
                    (item["email"], item["password"], item["totp_secret"]),
                )
                created += 1
    return {"parsed": len(parsed), "created": created, "updated": updated}


@router.get("/authorized-export")
def export_authorized_accounts():
    client_id = get_settings().microsoft_client_id
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT email, password, refresh_token
            FROM accounts
            WHERE refresh_token IS NOT NULL AND refresh_token != ''
            ORDER BY email
            """
        ).fetchall()

    lines = [
        f"{row['email']}----{row['password'] or ''}----{client_id}----{row['refresh_token']}"
        for row in rows
    ]
    return {"count": len(lines), "text": "\n".join(lines)}


@router.delete("/{account_id}")
def delete_account(account_id: int):
    with connect() as conn:
        cursor = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
    return {"deleted": True, "id": account_id}

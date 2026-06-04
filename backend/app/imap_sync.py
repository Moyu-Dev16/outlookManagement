from datetime import datetime
from email import message_from_bytes
from email.header import decode_header
from email.utils import parsedate_to_datetime
import imaplib

from fastapi import APIRouter, HTTPException

from .db import connect

router = APIRouter(prefix="/api/imap", tags=["imap"])

IMAP_HOST = "imap-mail.outlook.com"
IMAP_PORT = 993
MESSAGE_LIMIT_PER_FOLDER = 25


def decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def extract_text(message) -> str:
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if content_type == "text/plain" and disposition != "attachment":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""

    payload = message.get_payload(decode=True)
    if not payload:
        return ""
    return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        return None


def parse_list_response(line: bytes) -> tuple[str, str]:
    text = line.decode("utf-8", errors="replace")
    parts = text.rsplit(" ", 1)
    folder = parts[-1].strip().strip('"')
    return folder, folder


def fetch_recent_messages(mail: imaplib.IMAP4_SSL, folder_name: str):
    status, _ = mail.select(f'"{folder_name}"', readonly=True)
    if status != "OK":
        return []

    status, data = mail.search(None, "ALL")
    if status != "OK" or not data or not data[0]:
        return []

    message_ids = data[0].split()[-MESSAGE_LIMIT_PER_FOLDER:]
    messages = []
    for message_id in reversed(message_ids):
        status, fetched = mail.fetch(message_id, "(FLAGS BODY.PEEK[])")
        if status != "OK" or not fetched:
            continue
        flags = b" ".join(item if isinstance(item, bytes) else b"" for item in fetched)
        raw = next((item[1] for item in fetched if isinstance(item, tuple)), None)
        if not raw:
            continue

        parsed = message_from_bytes(raw)
        body = extract_text(parsed)
        messages.append(
            {
                "provider_message_id": parsed.get("Message-ID") or f"{folder_name}:{message_id.decode()}",
                "sender": decode_mime_header(parsed.get("From")),
                "subject": decode_mime_header(parsed.get("Subject")),
                "snippet": body[:300].replace("\r", " ").replace("\n", " ").strip(),
                "body": body,
                "received_at": normalize_date(parsed.get("Date")),
                "is_read": 1 if b"\\Seen" in flags else 0,
            }
        )
    return messages


@router.post("/accounts/{account_id}/sync")
def sync_account_via_imap(account_id: int):
    with connect() as conn:
        account = conn.execute(
            "SELECT id, email, password FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account["password"]:
        raise HTTPException(status_code=400, detail="Missing password or app password")

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=30)
        mail.login(account["email"], account["password"])
    except Exception as exc:
        with connect() as conn:
            conn.execute(
                "UPDATE accounts SET status = ?, last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                ("imap_failed", str(exc)[:500], account_id),
            )
        raise HTTPException(status_code=401, detail=f"IMAP login failed: {exc}") from exc

    synced_folders = 0
    synced_messages = 0
    try:
        status, folder_lines = mail.list()
        if status != "OK":
            raise HTTPException(status_code=502, detail="Failed to list IMAP folders")

        folders = [parse_list_response(line) for line in folder_lines or []]
        if not folders:
            folders = [("INBOX", "INBOX")]

        with connect() as conn:
            for provider_folder_id, display_name in folders:
                cursor = conn.execute(
                    """
                    INSERT INTO mail_folders (
                        account_id, provider_folder_id, display_name, synced_at
                    )
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(account_id, provider_folder_id) DO UPDATE SET
                        display_name = excluded.display_name,
                        synced_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (account_id, provider_folder_id, display_name),
                )
                local_folder_id = cursor.fetchone()["id"]
                synced_folders += 1

                for message in fetch_recent_messages(mail, provider_folder_id):
                    conn.execute(
                        """
                        INSERT INTO messages (
                            account_id, folder_id, provider_message_id, sender,
                            subject, snippet, body, received_at, is_read, synced_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(account_id, provider_message_id) DO UPDATE SET
                            folder_id = excluded.folder_id,
                            sender = excluded.sender,
                            subject = excluded.subject,
                            snippet = excluded.snippet,
                            body = excluded.body,
                            received_at = excluded.received_at,
                            is_read = excluded.is_read,
                            synced_at = CURRENT_TIMESTAMP
                        """,
                        (
                            account_id,
                            local_folder_id,
                            message["provider_message_id"],
                            message["sender"],
                            message["subject"],
                            message["snippet"],
                            message["body"],
                            message["received_at"],
                            message["is_read"],
                        ),
                    )
                    synced_messages += 1

            conn.execute(
                """
                UPDATE accounts
                SET status = ?, last_sync_at = CURRENT_TIMESTAMP, last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                ("imap_synced", account_id),
            )
            conn.execute(
                "INSERT INTO sync_logs (account_id, level, message) VALUES (?, ?, ?)",
                (
                    account_id,
                    "info",
                    f"IMAP synced {synced_folders} folders and {synced_messages} messages",
                ),
            )
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    return {
        "mode": "imap_app_password",
        "folders": synced_folders,
        "messages": synced_messages,
        "synced_at": datetime.utcnow().isoformat(),
    }

from pydantic import BaseModel, Field


class ImportAccountsRequest(BaseModel):
    text: str = Field(min_length=1)


class AccountOut(BaseModel):
    id: int
    email: str
    auth_mode: str
    status: str
    proxy_id: int | None = None
    last_sync_at: str | None = None
    last_error: str | None = None
    created_at: str


class FolderOut(BaseModel):
    id: int
    account_id: int
    provider_folder_id: str
    display_name: str
    well_known_name: str | None = None
    unread_count: int = 0
    total_count: int = 0
    synced_at: str | None = None


class MessageOut(BaseModel):
    id: int
    account_id: int
    folder_id: int | None = None
    sender: str | None = None
    subject: str | None = None
    snippet: str | None = None
    received_at: str | None = None
    is_read: bool = False

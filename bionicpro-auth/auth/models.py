from pydantic import BaseModel
from typing import Optional
import time

class SessionData(BaseModel):
    session_id: str
    user_id: str
    username: str
    email: str
    roles: list[str]
    access_token: str
    refresh_token: str
    access_token_expires_at: int  # timestamp
    refresh_token_expires_at: int
    created_at: int

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int

class SessionValidationResponse(BaseModel):
    valid: bool
    user_id: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    roles: Optional[list[str]] = None
    new_session_id: Optional[str] = None
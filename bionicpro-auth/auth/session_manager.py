import redis.asyncio as redis
import json
import uuid
import time
import base64
from typing import Optional, TYPE_CHECKING

from .models import SessionData, SessionValidationResponse
from config import settings

if TYPE_CHECKING:
    from .keycloak_client import KeycloakClient


def decode_jwt_payload(token: str) -> dict:
    """Декодирует JWT payload без проверки подписи"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError(f"Invalid JWT: expected 3 parts, got {len(parts)}")

        payload_part = parts[1]
        # Добавляем padding если нужно
        padding = 4 - (len(payload_part) % 4)
        if padding != 4:
            payload_part += '=' * padding

        decoded = base64.urlsafe_b64decode(payload_part)
        return json.loads(decoded)
    except Exception as e:
        raise ValueError(f"Failed to decode JWT: {e}")


class SessionManager:
    def __init__(self, keycloak_client: Optional['KeycloakClient'] = None):
        self.redis = None
        self.keycloak_client = keycloak_client

    async def connect(self):
        self.redis = await redis.from_url(settings.REDIS_URL, decode_responses=True)

    async def create_session(
        self,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        refresh_expires_in: int
    ) -> SessionData:
        """Создание сессии из токена"""
        try:
            # Декодируем токен
            token_payload = decode_jwt_payload(access_token)
            print(f"Decoded token payload: {json.dumps(token_payload, indent=2)}")
        except Exception as e:
            print(f"Failed to decode token: {e}")
            # Если не удалось декодировать, используем fallback
            token_payload = {}

        session_id = str(uuid.uuid4())
        now = int(time.time())

        # Извлекаем данные из токена
        user_id = token_payload.get("sub", "")
        username = token_payload.get("preferred_username", "")
        email = token_payload.get("email", "")

        # Роли могут быть в realm_access
        roles = token_payload.get("realm_access", {}).get("roles", [])
        if not roles:
            roles = token_payload.get("roles", [])

        print(f"User data: user_id={user_id}, username={username}, email={email}, roles={roles}")

        session = SessionData(
            session_id=session_id,
            user_id=user_id,
            username=username,
            email=email,
            roles=roles,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=now + expires_in,
            refresh_token_expires_at=now + refresh_expires_in,
            created_at=now
        )

        await self.redis.setex(
            f"session:{session_id}",
            settings.SESSION_TTL,
            session.model_dump_json()
        )

        return session

    async def get_session(self, session_id: str) -> Optional[SessionData]:
        """Получение сессии"""
        data = await self.redis.get(f"session:{session_id}")
        if data:
            return SessionData.model_validate_json(data)
        return None

    async def rotate_session(self, session_id: str) -> Optional[SessionData]:
        """Ротация сессии"""
        old_session = await self.get_session(session_id)
        if not old_session:
            return None

        await self.delete_session(session_id)

        new_session = SessionData(
            session_id=str(uuid.uuid4()),
            user_id=old_session.user_id,
            username=old_session.username,
            email=old_session.email,
            roles=old_session.roles,
            access_token=old_session.access_token,
            refresh_token=old_session.refresh_token,
            access_token_expires_at=old_session.access_token_expires_at,
            refresh_token_expires_at=old_session.refresh_token_expires_at,
            created_at=old_session.created_at
        )

        await self.redis.setex(
            f"session:{new_session.session_id}",
            settings.SESSION_TTL,
            new_session.model_dump_json()
        )

        return new_session

    async def update_session_tokens(
        self,
        session_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        refresh_expires_in: int
    ) -> Optional[SessionData]:
        """Обновление токенов в сессии"""
        session = await self.get_session(session_id)
        if not session:
            return None

        now = int(time.time())
        session.access_token = access_token
        session.refresh_token = refresh_token
        session.access_token_expires_at = now + expires_in
        session.refresh_token_expires_at = now + refresh_expires_in

        await self.redis.setex(
            f"session:{session_id}",
            settings.SESSION_TTL,
            session.model_dump_json()
        )

        return session

    async def delete_session(self, session_id: str):
        """Удаление сессии"""
        await self.redis.delete(f"session:{session_id}")

    async def validate_and_refresh(self, session_id: str) -> SessionValidationResponse:
        """Проверка сессии с автоматическим обновлением токенов"""
        session = await self.get_session(session_id)
        if not session:
            return SessionValidationResponse(valid=False)

        now = int(time.time())

        if session.access_token_expires_at <= now:
            if session.refresh_token_expires_at <= now:
                await self.delete_session(session_id)
                return SessionValidationResponse(valid=False)

            if not self.keycloak_client:
                await self.delete_session(session_id)
                return SessionValidationResponse(valid=False)

            try:
                tokens = await self.keycloak_client.refresh_token(session.refresh_token)

                session = await self.update_session_tokens(
                    session_id,
                    tokens["access_token"],
                    tokens["refresh_token"],
                    tokens["expires_in"],
                    tokens["refresh_expires_in"]
                )

                if not session:
                    return SessionValidationResponse(valid=False)

            except Exception as e:
                print(f"Failed to refresh tokens: {e}")
                await self.delete_session(session_id)
                return SessionValidationResponse(valid=False)

        # Ротация сессии
        new_session = await self.rotate_session(session_id)
        if new_session:
            return SessionValidationResponse(
                valid=True,
                user_id=new_session.user_id,
                username=new_session.username,
                email=new_session.email,
                roles=new_session.roles,
                new_session_id=new_session.session_id
            )
        
        return SessionValidationResponse(
            valid=True,
            user_id=session.user_id,
            username=session.username,
            email=session.email,
            roles=session.roles
        )
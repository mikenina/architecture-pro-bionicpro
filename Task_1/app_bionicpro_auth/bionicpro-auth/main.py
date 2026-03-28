from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from typing import Optional
import time

from config import settings, KEYCLOAK_AUTH_URL_EXTERNAL
from auth.keycloak_client import KeycloakClient
from auth.session_manager import SessionManager
from auth.models import SessionValidationResponse

app = FastAPI(title="bionicpro-auth")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация
keycloak = KeycloakClient()
session_manager = SessionManager(keycloak_client=keycloak)

@app.on_event("startup")
async def startup():
    await session_manager.connect()

# ========== Эндпоинты для фронтенда ==========

@app.get("/auth/login")
async def login_start():
    auth_url = (
        f"{KEYCLOAK_AUTH_URL_EXTERNAL}"
        f"?client_id={settings.KEYCLOAK_CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={settings.AUTH_CALLBACK_URL}"
        f"&scope=openid profile email"
    )
    return RedirectResponse(url=auth_url)

@app.get("/auth/callback")
async def auth_callback(
    response: Response,
    code: str = Query(...),
    session_state: Optional[str] = Query(None),
):
    try:
        tokens = await keycloak.exchange_code(
            code=code,
            redirect_uri=settings.AUTH_CALLBACK_URL
        )

        session = await session_manager.create_session(
            access_token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            expires_in=tokens["expires_in"],
            refresh_expires_in=tokens["refresh_expires_in"]
        )

        response.set_cookie(
            key="session_id",
            value=session.session_id,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=settings.SESSION_TTL,
            path="/"
        )

        # Временно возвращаем JSON вместо редиректа
        return {
            "success": True,
            "redirect_url": settings.FRONTEND_URL,
            "session_id": session.session_id,
            "user": {
                "username": session.username,
                "email": session.email
            }
        }

    except Exception as e:
        print(f"Error in auth_callback: {e}")
        return {"error": str(e)}

@app.get("/auth/me")
async def get_current_user(request: Request, response: Response):
    """
    Получение информации о текущем пользователе с ротацией сессии
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info(f"=== /auth/me called ===")
    logger.info(f"Cookies received: {request.cookies}")

    session_id = request.cookies.get("session_id")
    if not session_id:
        logger.warning("No session_id cookie found")
        raise HTTPException(status_code=401, detail="Not authenticated")

    logger.info(f"Session ID from cookie: {session_id}")

    session = await session_manager.get_session(session_id)
    if not session:
        logger.warning(f"Session not found in Redis: {session_id}")
        raise HTTPException(status_code=401, detail="Session expired")

    logger.info(f"Session found: user={session.username}, access_token_expires_at={session.access_token_expires_at}")

    # Проверяем access_token
    now = int(time.time())
    logger.info(f"Current time: {now}, Access token expires at: {session.access_token_expires_at}")

    if session.access_token_expires_at <= now:
        logger.info("Access token expired, attempting to refresh...")
        # Обновляем токены
        try:
            tokens = await keycloak.refresh_token(session.refresh_token)
            logger.info(f"Token refresh successful, new access_token expires_in={tokens['expires_in']}")

            session = await session_manager.update_session_tokens(
                session_id,
                tokens["access_token"],
                tokens["refresh_token"],
                tokens["expires_in"],
                tokens["refresh_expires_in"]
            )
            logger.info(f"Session tokens updated for session_id={session_id}")
        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            raise HTTPException(status_code=401, detail="Session expired")
    else:
        logger.info("Access token still valid")

    # Ротация сессии (создаем новый session_id)
    logger.info(f"Rotating session: old session_id={session_id}")
    new_session = await session_manager.rotate_session(session_id)

    if new_session:
        logger.info(f"Session rotated: new session_id={new_session.session_id}")
        # Обновляем cookie с новым session_id
        response.set_cookie(
            key="session_id",
            value=new_session.session_id,
            httponly=True,
            secure=False,
            samesite="lax",
            max_age=settings.SESSION_TTL,
            path="/"
        )
        logger.info(f"Cookie updated with new session_id={new_session.session_id}")

        return {
            "user_id": new_session.user_id,
            "username": new_session.username,
            "email": new_session.email,
            "roles": new_session.roles
        }

    logger.info("No rotation performed, returning existing session data")
    return {
        "user_id": session.user_id,
        "username": session.username,
        "email": session.email,
        "roles": session.roles
    }

@app.post("/auth/logout")
async def logout(request: Request, response: Response):
    """
    Выход из системы
    """
    session_id = request.cookies.get("session_id")
    if session_id:
        session = await session_manager.get_session(session_id)
        if session:
            await keycloak.logout(session.refresh_token)
            await session_manager.delete_session(session_id)
    
    response.delete_cookie("session_id")
    return {"success": True}

# ========== Эндпоинт для бизнес-сервисов ==========

@app.post("/session/validate")
async def validate_session(
    request: Request,
    session_id: Optional[str] = None
) -> SessionValidationResponse:
    """
    Валидация сессии для бизнес-сервисов
    """
    # Получаем session_id из cookie или из заголовка
    if not session_id:
        session_id = request.cookies.get("session_id")
    
    if not session_id:
        return SessionValidationResponse(valid=False)
    
    session = await session_manager.get_session(session_id)
    if not session:
        return SessionValidationResponse(valid=False)
    
    now = int(time.time())
    
    # Проверяем access_token, при необходимости обновляем
    if session.access_token_expires_at <= now:
        if session.refresh_token_expires_at <= now:
            await session_manager.delete_session(session_id)
            return SessionValidationResponse(valid=False)
        
        try:
            tokens = await keycloak.refresh_token(session.refresh_token)
            
            session = await session_manager.update_session_tokens(
                session_id,
                tokens["access_token"],
                tokens["refresh_token"],
                tokens["expires_in"],
                tokens["refresh_expires_in"]
            )
        except Exception:
            await session_manager.delete_session(session_id)
            return SessionValidationResponse(valid=False)
    
    # Ротация сессии (при каждом успешном запросе)
    new_session = await session_manager.rotate_session(session_id)
    
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
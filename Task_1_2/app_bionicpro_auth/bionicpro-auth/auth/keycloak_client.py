import httpx
import logging
from typing import Dict, Any
from config import settings, KEYCLOAK_TOKEN_URL, KEYCLOAK_USERINFO_URL, KEYCLOAK_LOGOUT_URL

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KeycloakClient:
    def __init__(self):
        self.token_url = KEYCLOAK_TOKEN_URL
        self.userinfo_url = KEYCLOAK_USERINFO_URL
        self.logout_url = KEYCLOAK_LOGOUT_URL
        self.client_id = settings.KEYCLOAK_CLIENT_ID
        self.client_secret = settings.KEYCLOAK_CLIENT_SECRET

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        logger.info(f"Exchanging code at: {self.token_url}")
        logger.info(f"Client ID: {self.client_id}")

        async with httpx.AsyncClient() as client:
            data = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            logger.info(f"Request data: { {k: v for k, v in data.items() if k != 'client_secret'} }")

            response = await client.post(
                self.token_url,
                data=data
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")

            response.raise_for_status()
            return response.json()

    async def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Обновление access_token через refresh_token"""
        logger.info(f"Refreshing token at: {self.token_url}")

        async with httpx.AsyncClient() as client:
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }

            response = await client.post(
                self.token_url,
                data=data
            )

            logger.info(f"Refresh token response status: {response.status_code}")
            logger.info(f"Refresh token response: {response.text}")

            response.raise_for_status()
            return response.json()

    async def get_user_info(self, access_token: str) -> Dict[str, Any]:
        logger.info(f"Getting user info at: {self.userinfo_url}")
        logger.info(f"Access token (first 20 chars): {access_token[:20]}...")

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            logger.info(f"Userinfo response status: {response.status_code}")
            logger.info(f"Userinfo response body: {response.text}")

            response.raise_for_status()
            return response.json()

    async def logout(self, refresh_token: str) -> None:
        logger.info(f"Logging out at: {self.logout_url}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.logout_url,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                }
            )
            logger.info(f"Logout response status: {response.status_code}")
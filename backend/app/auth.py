"""API key authentication dependency."""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional

from app.settings import settings

security = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    """Verify the API key from the Authorization header.

    Expects: Authorization: Bearer <API_KEY>
    Returns the key string if valid.
    Raises 401 if missing or invalid.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
        
    return credentials.credentials
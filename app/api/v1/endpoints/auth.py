from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.security import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/me", summary="Get authenticated user identity")
async def get_authenticated_user(
    current_user: Annotated[
        AuthenticatedUser,
        Depends(get_current_user),
    ],
) -> dict[str, str | None]:
    return {
        "sub": current_user.sub,
        "client_id": current_user.client_id,
        "token_use": current_user.token_use,
        "scope": current_user.scope,
    }

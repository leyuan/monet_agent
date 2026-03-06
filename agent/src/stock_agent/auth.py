"""Authentication for the Stock Agent.

Validates Supabase JWT tokens from the frontend via the Authorization header.
"""

import os

import httpx
from langgraph_sdk import Auth

auth = Auth()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


@auth.authenticate
async def authenticate(headers: dict[bytes, bytes]) -> Auth.types.MinimalUserDict:
    """Validate Supabase JWT and return the user's identity."""
    authorization = headers.get(b"authorization", b"").decode()
    if not authorization or not authorization.startswith("Bearer "):
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={
                    "Authorization": authorization,
                    "apiKey": SUPABASE_SERVICE_ROLE_KEY,
                },
            )
            if response.status_code != 200:
                raise Auth.exceptions.HTTPException(
                    status_code=401, detail="Invalid or expired token"
                )
            user = response.json()
    except Auth.exceptions.HTTPException:
        raise
    except Exception as exc:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail=f"Authentication failed: {exc}"
        )

    return {
        "identity": user["id"],
        "email": user.get("email"),
        "permissions": ["user"],
    }


@auth.on
async def add_owner(
    ctx: Auth.types.AuthContext,
    value: dict,
) -> dict:
    """Tag resources with owner on create; filter by owner on search."""
    filters = {"owner": ctx.user.identity}
    metadata = value.setdefault("metadata", {})
    metadata.update(filters)
    return filters

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
        # Allow unauthenticated access in local dev (Studio uses no-op auth)
        if os.environ.get("LANGGRAPH_ENV", "dev") == "dev":
            return {"identity": "dev-user", "permissions": ["user"]}
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
    """Tag resources with owner on create; filter by owner on search.

    If the caller is a service-level identity (dev-user) and the resource
    already has an explicit owner in metadata, preserve that owner instead
    of overwriting it. This allows autonomous tools (e.g. send_daily_recap)
    to create threads on behalf of a specific user.
    """
    metadata = value.setdefault("metadata", {})
    # If service-level caller explicitly set an owner, respect it
    if ctx.user.identity == "dev-user" and metadata.get("owner"):
        owner = metadata["owner"]
    else:
        owner = ctx.user.identity
        metadata["owner"] = owner
    return {"owner": owner}

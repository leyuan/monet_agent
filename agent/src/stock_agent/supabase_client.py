"""Shared Supabase client singleton."""

import os

from supabase import Client, create_client

_supabase_client: Client | None = None


def get_supabase() -> Client:
    """Get or create the Supabase client (lazy singleton)."""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase_client

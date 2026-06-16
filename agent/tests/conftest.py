import os
import pytest


def pytest_collection_modifyitems(config, items):
    """Skip @pytest.mark.integration tests unless RUN_DB_INTEGRATION=1 is set."""
    if os.environ.get("RUN_DB_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="DB integration tests: set RUN_DB_INTEGRATION=1 + a local SUPABASE_URL to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def local_supabase():
    """Yield a Supabase client ONLY when pointed at a local DB. Prod-safety guard:
    refuse to run integration tests against any non-local SUPABASE_URL."""
    url = os.environ.get("SUPABASE_URL", "")
    if not ("127.0.0.1" in url or "localhost" in url):
        pytest.skip("integration tests require a LOCAL SUPABASE_URL (refusing non-local)")
    from common.supabase_client import get_supabase
    return get_supabase()

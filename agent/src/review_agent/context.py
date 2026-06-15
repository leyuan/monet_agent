"""Per-run context for the reviewer — binds the active review type so memory
writes are namespaced to it (the LLM cannot write an arbitrary namespace)."""
from contextvars import ContextVar

active_review_type: ContextVar[str | None] = ContextVar("active_review_type", default=None)

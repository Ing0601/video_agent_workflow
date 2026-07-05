"""Backward-compatible wrapper for the session store implementation."""

from ..session_store import MySQLAbstractor, SessionStore

__all__ = ["SessionStore", "MySQLAbstractor"]

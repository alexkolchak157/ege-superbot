# task24/__init__.py
"""Initialization for task24 module."""

try:
    from .plugin import plugin
except Exception:  # pragma: no cover - optional plugin import
    plugin = None

__all__ = ['plugin']

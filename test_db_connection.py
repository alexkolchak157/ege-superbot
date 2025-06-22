import os
import sys
import pytest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Provide dummy token to satisfy config import
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")

from core import db

@pytest.mark.asyncio
async def test_open_and_close_db():
    conn = await db.get_db()
    assert conn is not None
    await db.close_db()
    assert db._db is None

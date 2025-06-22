import pytest
from task19 import handlers
from core.admin_tools import admin_manager

class DummyQuery:
    def __init__(self):
        self.from_user = type('User', (), {'id': 1})()
    async def answer(self, *args, **kwargs):
        pass
    async def edit_message_text(self, *args, **kwargs):
        pass

class DummyUpdate:
    def __init__(self):
        self.callback_query = DummyQuery()

class DummyContext:
    pass

@pytest.mark.asyncio
async def test_strictness_menu_no_nameerror(monkeypatch):
    monkeypatch.setattr(admin_manager, "is_admin", lambda uid: True)
    update = DummyUpdate()
    context = DummyContext()
    try:
        await handlers.strictness_menu(update, context)
    except NameError as e:
        pytest.fail(f"strictness_menu raised NameError: {e}")


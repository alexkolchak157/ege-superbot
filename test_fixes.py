#!/usr/bin/env python3
"""
Тесты для проверки критических исправлений в боте.
"""

import asyncio
import sys
import os
from unittest.mock import Mock, AsyncMock, patch
import pytest

# Добавляем корневую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestSQLInjectionFixes:
    """Тесты защиты от SQL injection."""
    
    @pytest.mark.asyncio
    async def test_sql_injection_protection(self):
        """Проверка защиты от SQL injection в core.db."""
        from core import db
        
        # Тест с опасными входными данными
        malicious_inputs = [
            "1; DROP TABLE users;--",
            "' OR '1'='1",
            "1 UNION SELECT * FROM users",
            "'; DELETE FROM user_progress WHERE '1'='1"
        ]
        
        for malicious_input in malicious_inputs:
            # Должны безопасно обработать без выполнения вредоносного кода
            try:
                # Пробуем с невалидным user_id
                result = await db.get_user_stats(malicious_input)
                assert result == []  # Должен вернуть пустой результат
                
                # Пробуем с string вместо int
                result = await db.update_progress(malicious_input, "test", True)
                assert result is None  # Должен отклонить
                
            except Exception as e:
                pytest.fail(f"SQL injection protection failed: {e}")
        
        print("✅ SQL injection protection test passed")


class TestAdminValidation:
    """Тесты валидации админских ID."""
    
    def test_admin_id_validation(self):
        """Проверка валидации admin IDs."""
        from core.admin_tools import AdminManager
        
        admin_manager = AdminManager()
        
        # Тест валидных ID
        valid_ids = ["123456789", "987654321", " 555555 "]
        for admin_id in valid_ids:
            result = admin_manager._validate_admin_id(admin_id)
            assert isinstance(result, int) and result > 0
        
        # Тест невалидных ID
        invalid_ids = [
            "abc",
            "12.34",
            "!@#",
            "",
            None,
            "99999999999999999999",  # Слишком большой
            "-123",  # Отрицательный
            "0"  # Ноль
        ]
        
        for admin_id in invalid_ids:
            result = admin_manager._validate_admin_id(str(admin_id) if admin_id else "")
            assert result is None
        
        print("✅ Admin ID validation test passed")


class TestErrorHandling:
    """Тесты системы обработки ошибок."""
    
    @pytest.mark.asyncio
    async def test_safe_handler_decorator(self):
        """Проверка работы декоратора safe_handler."""
        from core.error_handler import safe_handler
        from telegram import Update
        from telegram.ext import ContextTypes, ConversationHandler
        
        # Создаем тестовый обработчик с ошибкой
        @safe_handler(return_on_error=ConversationHandler.END)
        async def failing_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            raise ValueError("Test error")
        
        # Мокаем Update и Context
        update = Mock(spec=Update)
        update.effective_user = Mock(id=12345)
        update.callback_query = None
        update.message = AsyncMock()
        
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot_data = {}
        
        # Вызываем обработчик
        result = await failing_handler(update, context)
        
        # Должен вернуть ConversationHandler.END при ошибке
        assert result == ConversationHandler.END
        
        # Должен вызвать reply_text с сообщением об ошибке
        update.message.reply_text.assert_called_once()
        
        print("✅ Error handling test passed")
    
    @pytest.mark.asyncio  
    async def test_callback_answerer(self):
        """Проверка CallbackAnswerer."""
        from core.error_handler import CallbackAnswerer
        
        # Мокаем callback_query
        query = AsyncMock()
        query.answer = AsyncMock()
        
        # Тест успешного выполнения
        async with CallbackAnswerer(query) as answerer:
            # Должен ответить при входе
            query.answer.assert_called_once_with("Обработка...")
        
        # Тест с ошибкой
        query.answer.reset_mock()
        try:
            async with CallbackAnswerer(query) as answerer:
                raise ValueError("Test error")
        except ValueError:
            pass
        
        # Должен ответить с ошибкой при исключении
        assert query.answer.call_count >= 1
        
        print("✅ CallbackAnswerer test passed")


class TestEvaluatorSafety:
    """Тесты безопасной работы с evaluator."""
    
    @pytest.mark.asyncio
    async def test_none_evaluator_handling(self):
        """Проверка обработки None evaluator."""
        from core.safe_evaluator import SafeEvaluatorMixin
        from telegram import Update, Message
        from telegram.ext import ContextTypes
        
        # Мокаем необходимые объекты
        update = Mock(spec=Update)
        update.effective_user = Mock(id=12345)
        update.message = AsyncMock(spec=Message)
        
        context = Mock(spec=ContextTypes.DEFAULT_TYPE)
        
        # Тест с None evaluator
        result = await SafeEvaluatorMixin.safe_evaluate(
            evaluator=None,  # None evaluator
            user_answer="Test answer",
            topic={"title": "Test topic"},
            task_number=19,
            update=update,
            context=context
        )
        
        # Должен вернуть fallback результат
        assert result['success'] is True
        assert result['score'] >= 0
        assert 'feedback' in result
        assert 'fallback' in result['feedback'].lower()
        
        print("✅ None evaluator handling test passed")


class TestAIServiceRetry:
    """Тесты retry логики AI сервиса."""
    
    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Проверка экспоненциальной задержки при повторах."""
        from core.ai_service import YandexGPTService, YandexGPTConfig
        import aiohttp
        
        # Конфигурация с 3 попытками
        config = YandexGPTConfig(
            api_key="test_key",
            folder_id="test_folder",
            retries=3,
            retry_delay=0.1,  # Короткая задержка для теста
            timeout=5
        )
        
        # Счетчик попыток
        attempts = 0
        
        # Мокаем aiohttp для симуляции ошибок
        async def mock_post(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise aiohttp.ClientError("Network error")
            # Успех на 3-й попытке
            return AsyncMock(
                status=200,
                json=AsyncMock(return_value={
                    "result": {
                        "alternatives": [{"message": {"text": "Success"}}],
                        "usage": {}
                    }
                })
            )
        
        with patch('aiohttp.ClientSession.post', mock_post):
            async with YandexGPTService(config) as service:
                result = await service.get_completion("test prompt")
        
        assert attempts == 3
        assert result['success'] is True
        assert result['text'] == "Success"
        
        print("✅ AI service retry test passed")


class TestPluginLoading:
    """Тесты загрузки плагинов."""
    
    def test_dynamic_plugin_loading(self):
        """Проверка динамической загрузки плагинов."""
        from core.plugin_loader import discover_plugins, PLUGINS
        
        # Очищаем список плагинов
        PLUGINS.clear()
        
        # Загружаем плагины
        discover_plugins()
        
        # Проверяем, что плагины загружены
        assert len(PLUGINS) > 0
        
        # Проверяем наличие основных плагинов
        plugin_codes = [p.code for p in PLUGINS]
        expected_plugins = ['test_part', 'task19', 'task20', 'task24', 'task25']
        
        for expected in expected_plugins:
            assert expected in plugin_codes, f"Plugin {expected} not loaded"
        
        # Проверяем сортировку по приоритету
        priorities = [p.menu_priority for p in PLUGINS]
        assert priorities == sorted(priorities)
        
        print("✅ Plugin loading test passed")


class TestStateValidation:
    """Тесты валидации состояний."""
    
    def test_state_transitions(self):
        """Проверка допустимых переходов состояний."""
        from core.state_validator import StateTransitionValidator
        from core import states
        from telegram.ext import ConversationHandler
        
        validator = StateTransitionValidator()
        
        # Тест допустимых переходов
        valid_transitions = [
            (states.CHOOSING_MODE, states.CHOOSING_BLOCK),
            (states.CHOOSING_BLOCK, states.CHOOSING_TOPIC),
            (states.CHOOSING_TOPIC, states.ANSWERING),
            (states.ANSWERING, states.CHOOSING_NEXT_ACTION),
            (states.CHOOSING_MODE, ConversationHandler.END),
        ]
        
        for from_state, to_state in valid_transitions:
            assert validator.is_valid_transition(123, from_state, to_state)
        
        # Тест недопустимых переходов
        invalid_transitions = [
            (states.ANSWERING, states.CHOOSING_BLOCK),  # Нельзя из ответа в выбор блока
            (states.REVIEWING_MISTAKES, states.CHOOSING_EXAM_NUMBER),
        ]
        
        for from_state, to_state in invalid_transitions:
            assert not validator.is_valid_transition(123, from_state, to_state)
        
        print("✅ State validation test passed")


async def run_all_tests():
    """Запуск всех тестов."""
    print("🧪 Запуск тестов критических исправлений...\n")
    
    # SQL Injection
    sql_test = TestSQLInjectionFixes()
    await sql_test.test_sql_injection_protection()
    
    # Admin validation
    admin_test = TestAdminValidation()
    admin_test.test_admin_id_validation()
    
    # Error handling
    error_test = TestErrorHandling()
    await error_test.test_safe_handler_decorator()
    await error_test.test_callback_answerer()
    
    # Evaluator safety
    eval_test = TestEvaluatorSafety()
    await eval_test.test_none_evaluator_handling()
    
    # AI service retry
    ai_test = TestAIServiceRetry()
    await ai_test.test_exponential_backoff()
    
    # Plugin loading
    plugin_test = TestPluginLoading()
    plugin_test.test_dynamic_plugin_loading()
    
    # State validation
    state_test = TestStateValidation()
    state_test.test_state_transitions()
    
    print("\n✨ Все тесты пройдены успешно!")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
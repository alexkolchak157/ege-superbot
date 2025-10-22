"""
Freemium менеджер для управления лимитами AI-проверок.

ВАЖНО: Этот модуль является заглушкой.
Полноценный функционал freemium/лимитов пока не реализован.
В текущей версии возвращает неограниченный доступ.
"""

import logging
from typing import Tuple, Dict, Optional, Any

logger = logging.getLogger(__name__)


class FreemiumManager:
    """Менеджер для управления лимитами freemium пользователей (заглушка)"""

    def __init__(self, subscription_manager=None):
        """
        Инициализация менеджера.

        Args:
            subscription_manager: Менеджер подписок (опционально)
        """
        self.subscription_manager = subscription_manager
        logger.warning("FreemiumManager initialized as stub - unlimited access enabled")

    async def check_ai_limit(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> Tuple[bool, int, str]:
        """
        Проверка доступности AI-проверки для пользователя.

        Args:
            user_id: ID пользователя
            module_code: Код модуля (например, 'task19', 'task24')

        Returns:
            Tuple: (can_use, remaining, limit_msg)
                - can_use: Может ли пользователь использовать AI-проверку
                - remaining: Сколько проверок осталось
                - limit_msg: Сообщение о лимитах
        """
        # Заглушка: всегда разрешаем использование
        return (True, 999, "✅ Доступ разрешен")

    async def get_limit_info(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получение информации о лимитах пользователя.

        Args:
            user_id: ID пользователя
            module_code: Код модуля (опционально)

        Returns:
            Dict с информацией о лимитах
        """
        # Заглушка: возвращаем информацию о "премиум" пользователе
        return {
            'is_premium': True,
            'has_subscription': True,
            'checks_remaining': 999,
            'checks_limit': 999,
            'reset_date': None,
            'module_code': module_code
        }

    def format_limit_message(self, limit_info: Dict[str, Any]) -> str:
        """
        Форматирование сообщения о лимитах.

        Args:
            limit_info: Информация о лимитах

        Returns:
            Отформатированное сообщение
        """
        # Заглушка: возвращаем простое сообщение
        if limit_info.get('is_premium'):
            return "✨ <b>Premium доступ активен</b>"
        else:
            remaining = limit_info.get('checks_remaining', 0)
            limit = limit_info.get('checks_limit', 0)
            return f"🔢 Осталось проверок: {remaining}/{limit}"

    async def use_ai_check(
        self,
        user_id: int,
        module_code: Optional[str] = None
    ) -> bool:
        """
        Регистрация использования AI-проверки.

        Args:
            user_id: ID пользователя
            module_code: Код модуля

        Returns:
            True если использование зарегистрировано успешно
        """
        # Заглушка: всегда возвращаем успех
        logger.debug(f"AI check used by user {user_id} for module {module_code}")
        return True

    async def reset_daily_limits(self) -> int:
        """
        Сброс дневных лимитов для всех пользователей.

        Returns:
            Количество пользователей, для которых сброшены лимиты
        """
        # Заглушка: ничего не делаем
        return 0

    async def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Получение статистики использования для пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Словарь со статистикой
        """
        # Заглушка: возвращаем пустую статистику
        return {
            'total_checks': 0,
            'checks_today': 0,
            'modules_used': []
        }


# Глобальный экземпляр менеджера
_freemium_manager_instance: Optional[FreemiumManager] = None


def get_freemium_manager(subscription_manager=None) -> FreemiumManager:
    """
    Получение глобального экземпляра freemium менеджера.

    Args:
        subscription_manager: Менеджер подписок (опционально)

    Returns:
        Экземпляр FreemiumManager
    """
    global _freemium_manager_instance

    if _freemium_manager_instance is None:
        _freemium_manager_instance = FreemiumManager(subscription_manager)

    return _freemium_manager_instance

"""
Конфигурация и оптимизация YandexGPT для проверки заданий ЕГЭ
"""

import os
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class TaskType(Enum):
    """Типы заданий ЕГЭ"""
    TASK_19 = "task19"  # Примеры
    TASK_20 = "task20"  # Суждения
    TASK_25 = "task25"  # Обоснование и примеры
    TASK_24 = "task24"  # План (для проверки планов)


@dataclass
class OptimalSettings:
    """Оптимальные настройки для разных типов заданий"""
    temperature: float
    max_tokens: int
    model: str
    
    @classmethod
    def for_task(cls, task_type: TaskType) -> 'OptimalSettings':
        """Возвращает оптимальные настройки для типа задания"""
        
        settings_map = {
            TaskType.TASK_19: cls(
                temperature=0.2,  # Низкая для точности оценки примеров
                max_tokens=2000,
                model="yandexgpt"  # Pro версия для лучшего понимания контекста
            ),
            TaskType.TASK_20: cls(
                temperature=0.3,  # Чуть выше для оценки абстрактных суждений
                max_tokens=2000,
                model="yandexgpt"
            ),
            TaskType.TASK_25: cls(
                temperature=0.2,  # Низкая для комплексной оценки
                max_tokens=3000,  # Больше токенов для развёрнутого анализа
                model="yandexgpt"
            ),
            TaskType.TASK_24: cls(
                temperature=0.1,  # Минимальная для структурного анализа
                max_tokens=2500,
                model="yandexgpt"
            )
        }
        
        return settings_map.get(task_type, cls(0.3, 2000, "yandexgpt"))


class PromptOptimizer:
    """Оптимизация промптов для YandexGPT"""
    
    @staticmethod
    def optimize_for_yandex(prompt: str) -> str:
        """Адаптирует промпт под особенности YandexGPT"""
        
        # 1. Структурирование
        prompt = PromptOptimizer._add_clear_structure(prompt)
        
        # 2. Упрощение языка
        prompt = PromptOptimizer._simplify_language(prompt)
        
        # 3. Добавление ключевых слов
        prompt = PromptOptimizer._add_keywords(prompt)
        
        # 4. Оптимизация длины
        prompt = PromptOptimizer._optimize_length(prompt)
        
        return prompt
    
    @staticmethod
    def _add_clear_structure(prompt: str) -> str:
        """Добавляет чёткую структуру"""
        # YandexGPT лучше работает с явной структурой
        if "ФОРМАТ ОТВЕТА" not in prompt:
            prompt += "\n\nФОРМАТ ОТВЕТА: структурированный JSON"
        return prompt
    
    @staticmethod
    def _simplify_language(prompt: str) -> str:
        """Упрощает слишком сложные конструкции"""
        replacements = {
            "осуществить комплексный анализ": "проанализировать",
            "продемонстрировать наличие": "показать",
            "реализовать проверку": "проверить"
        }
        
        for old, new in replacements.items():
            prompt = prompt.replace(old, new)
        
        return prompt
    
    @staticmethod
    def _add_keywords(prompt: str) -> str:
        """Добавляет ключевые слова для лучшего понимания"""
        keywords = {
            "ЕГЭ": "единый государственный экзамен",
            "ФИПИ": "Федеральный институт педагогических измерений",
            "балл": "оценка в баллах"
        }
        
        # Добавляем расшифровки в начало если их нет
        for abbr, full in keywords.items():
            if abbr in prompt and full not in prompt:
                prompt = f"{abbr} ({full})\n" + prompt
                break
        
        return prompt
    
    @staticmethod
    def _optimize_length(prompt: str, max_length: int = 8000) -> str:
        """Оптимизирует длину промпта"""
        if len(prompt) > max_length:
            # Сокращаем менее важные части
            logger.warning(f"Промпт слишком длинный ({len(prompt)} символов), сокращаем")
            # Логика сокращения
            return prompt[:max_length] + "..."
        return prompt


class CostCalculator:
    """Калькулятор стоимости использования YandexGPT"""
    
    # Примерные тарифы YandexGPT (на момент 2024)
    PRICES = {
        "yandexgpt-lite": {
            "input": 0.2,   # руб. за 1000 токенов
            "output": 0.4   # руб. за 1000 токенов
        },
        "yandexgpt": {
            "input": 2.0,   # руб. за 1000 токенов
            "output": 4.0   # руб. за 1000 токенов
        }
    }
    
    @classmethod
    def estimate_cost(
        cls,
        task_type: TaskType,
        answers_count: int,
        avg_answer_length: int = 500
    ) -> Dict[str, float]:
        """Оценка стоимости проверки"""
        
        settings = OptimalSettings.for_task(task_type)
        model = settings.model
        
        # Примерный расчёт токенов
        avg_prompt_tokens = 1500  # Средний размер промпта
        avg_response_tokens = 800  # Средний размер ответа
        
        # Токены на один ответ
        input_tokens = avg_prompt_tokens + (avg_answer_length // 4)
        output_tokens = avg_response_tokens
        
        # Стоимость за один ответ
        cost_per_answer = (
            (input_tokens / 1000) * cls.PRICES[model]["input"] +
            (output_tokens / 1000) * cls.PRICES[model]["output"]
        )
        
        # Общая стоимость
        total_cost = cost_per_answer * answers_count
        
        return {
            "cost_per_answer": round(cost_per_answer, 2),
            "total_cost": round(total_cost, 2),
            "model": model,
            "answers_count": answers_count
        }


class RateLimiter:
    """Управление лимитами запросов"""
    
    def __init__(self, requests_per_minute: int = 100):
        self.rpm_limit = requests_per_minute
        self.request_times = []
    
    async def wait_if_needed(self):
        """Ожидание если превышен лимит"""
        import asyncio
        from datetime import datetime, timedelta
        
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        # Очищаем старые записи
        self.request_times = [t for t in self.request_times if t > minute_ago]
        
        # Проверяем лимит
        if len(self.request_times) >= self.rpm_limit:
            # Ждём до истечения минуты
            wait_time = (self.request_times[0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logger.info(f"Достигнут лимит запросов, ожидание {wait_time:.1f} сек")
                await asyncio.sleep(wait_time)
        
        self.request_times.append(now)


# Глобальные настройки
YANDEX_GPT_CONFIG = {
    "base_url": "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
    "timeout": 60,  # секунд
    "retry_attempts": 3,
    "retry_delay": 2,  # секунд
    
    # Лимиты
    "rate_limit": {
        "requests_per_minute": 100,
        "tokens_per_minute": 120000
    },
    
    # Настройки по умолчанию
    "default_settings": {
        "temperature": 0.3,
        "max_tokens": 2000,
        "top_p": 0.95,
        "stream": False
    },
    
    # Специальные настройки для обществознания
    "social_studies_context": {
        "knowledge_cutoff": "2024",
        "russian_focus": True,
        "use_academic_style": True
    }
}


# Функции-помощники
def get_optimal_config(task_type: TaskType) -> Dict[str, Any]:
    """Получает оптимальную конфигурацию для задания"""
    settings = OptimalSettings.for_task(task_type)
    
    return {
        "modelUri": f"gpt://{os.getenv('YANDEX_GPT_FOLDER_ID')}/{settings.model}",
        "completionOptions": {
            "temperature": settings.temperature,
            "maxTokens": str(settings.max_tokens),
            "stream": False
        }
    }


def estimate_monthly_cost(
    daily_users: int,
    tasks_per_user: int = 5,
    task_distribution: Dict[TaskType, float] = None
) -> Dict[str, Any]:
    """Оценка месячной стоимости сервиса"""
    
    if task_distribution is None:
        # Примерное распределение заданий
        task_distribution = {
            TaskType.TASK_19: 0.4,
            TaskType.TASK_20: 0.3,
            TaskType.TASK_25: 0.3
        }
    
    monthly_answers = daily_users * tasks_per_user * 30
    total_cost = 0
    
    breakdown = {}
    for task_type, percentage in task_distribution.items():
        task_answers = int(monthly_answers * percentage)
        task_cost = CostCalculator.estimate_cost(task_type, task_answers)
        breakdown[task_type.value] = task_cost
        total_cost += task_cost["total_cost"]
    
    return {
        "monthly_cost": round(total_cost, 2),
        "daily_cost": round(total_cost / 30, 2),
        "cost_per_user": round(total_cost / (daily_users * 30), 2),
        "breakdown": breakdown,
        "total_answers": monthly_answers
    }


# Рекомендации по использованию
OPTIMIZATION_TIPS = """
РЕКОМЕНДАЦИИ ПО ОПТИМИЗАЦИИ YandexGPT ДЛЯ ЕГЭ:

1. ВЫБОР МОДЕЛИ:
   - yandexgpt-lite: для простых проверок (задание 19)
   - yandexgpt: для сложных заданий (20, 25) и высокой точности

2. ТЕМПЕРАТУРА:
   - 0.1-0.2: проверка фактов, структуры (задания 19, 24)
   - 0.2-0.3: оценка суждений (задание 20)
   - 0.3-0.5: генерация обратной связи

3. ОПТИМИЗАЦИЯ ПРОМПТОВ:
   - Чёткая структура с разделами
   - Конкретные критерии оценки
   - Примеры правильных ответов
   - JSON для структурированного вывода

4. ЭКОНОМИЯ СРЕДСТВ:
   - Кэширование частых запросов
   - Батчинг похожих заданий
   - Использование lite-модели где возможно
   - Предварительная фильтрация простых случаев

5. ПОВЫШЕНИЕ КАЧЕСТВА:
   - Добавление российского контекста
   - Использование актуальных данных
   - Валидация ответов на стороне кода
   - A/B тестирование промптов
"""

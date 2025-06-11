import asyncio
import aiohttp
import json
from typing import Dict, Any
import logging

from config import API_KEY_YANDEX, FOLDER_ID

logger = logging.getLogger(__name__)


async def check_task20(task_text: str, student_answer: str) -> Dict[str, Any]:
    """
    Проверка задания 20 ЕГЭ по обществознанию через YandexGPT API.
    
    Args:
        task_text: Текст задания
        student_answer: Ответ ученика
        
    Returns:
        Dict с результатами проверки
    """
    
    prompt = f"""Ты - эксперт ЕГЭ по обществознанию. Проверь задание 20.

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 20:
1. В отличие от задания 19, здесь НЕ нужны конкретные примеры
2. Требуются аргументы АБСТРАКТНОГО характера с элементами обобщения
3. Аргументы должны быть более широкого объёма и менее конкретного содержания
4. Каждый аргумент должен быть сформулирован как распространённое предложение
5. Суждения должны содержать элементы обобщения

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 3 балла: приведены все требуемые аргументы правильного типа
- 2 балла: приведено на один аргумент меньше требуемого
- 1 балл: приведено на два аргумента меньше требуемого  
- 0 баллов: приведен только один аргумент ИЛИ рассуждения общего характера

ШТРАФЫ:
- Если наряду с требуемыми аргументами есть 2+ дополнительных с ошибками → 0 баллов
- Если есть 1 дополнительный с ошибкой → минус 1 балл от фактического

ЧТО СЧИТАЕТСЯ ПРАВИЛЬНЫМ АРГУМЕНТОМ ДЛЯ ЗАДАНИЯ 20:
- Содержит элементы обобщения (способствует, приводит к, влияет на, обеспечивает, позволяет, создает, формирует, развивает, препятствует, ограничивает, снижает, повышает, улучшает, ухудшает, определяет, зависит от)
- НЕ содержит конкретных примеров (дат, имён, названий конкретных стран/организаций/компаний)
- Является распространённым предложением (не менее 5 слов)
- Соответствует требованию задания (подтверждающий/опровергающий/положительный/негативный)
- Содержит причинно-следственные связи

ЧТО НЕ ЗАСЧИТЫВАЕТСЯ:
- Конкретные примеры (например: "В 2020 году в России...", "Компания Apple...", "Во Франции...")
- Упоминание конкретных личностей, дат, событий
- Слишком конкретное содержание без обобщения
- Отдельные слова и словосочетания
- Общие рассуждения без чёткой аргументации
- Аргументы, не соответствующие типу (например, негативный вместо позитивного)

ЗАДАНИЕ:
{task_text}

ОТВЕТ УЧЕНИКА:
{student_answer}

Проанализируй ответ и верни JSON со следующей структурой:
{{
    "score": число от 0 до 3,
    "max_score": 3,
    "required_arguments": количество требуемых аргументов,
    "valid_arguments_count": количество засчитанных аргументов,
    "penalty_applied": true/false,
    "penalty_reason": "причина штрафа" или null,
    "valid_arguments": [
        {{
            "number": номер аргумента,
            "text": "текст аргумента",
            "type": "positive/negative/general",
            "has_generalization": true/false,
            "comment": "почему засчитан"
        }}
    ],
    "invalid_arguments": [
        {{
            "number": номер аргумента,
            "text": "текст аргумента", 
            "reason": "почему не засчитан",
            "is_concrete_example": true/false
        }}
    ],
    "comment": "общий комментарий по проверке",
    "recommendations": ["список рекомендаций для улучшения"]
}}

ВАЖНО: Верни ТОЛЬКО валидный JSON без дополнительного текста."""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {API_KEY_YANDEX}"
    }
    
    data = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.1,
            "maxTokens": 2000
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты - эксперт по проверке заданий ЕГЭ по обществознанию. Всегда возвращай ответ в формате JSON."
            },
            {
                "role": "user", 
                "text": prompt
            }
        ]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
                headers=headers,
                json=data,
                ssl=False
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"YandexGPT API error: {response.status} - {error_text}")
                    return {
                        "error": f"API error: {response.status}",
                        "details": error_text,
                        "score": 0,
                        "max_score": 3,
                        "comment": "Ошибка при проверке задания"
                    }
                
                result = await response.json()
                
                try:
                    # Извлекаем текст ответа
                    response_text = result['result']['alternatives'][0]['message']['text']
                    
                    # Парсим JSON
                    evaluation = json.loads(response_text)
                    
                    # Добавляем дополнительную информацию
                    evaluation['task_type'] = 'task20'
                    
                    # Проверяем обязательные поля
                    required_fields = ['score', 'max_score', 'required_arguments', 'valid_arguments_count']
                    for field in required_fields:
                        if field not in evaluation:
                            logger.error(f"Missing required field: {field}")
                            evaluation[field] = 0 if 'score' in field or 'count' in field else 3
                    
                    # Проверяем корректность score
                    if not isinstance(evaluation['score'], int) or evaluation['score'] < 0 or evaluation['score'] > 3:
                        logger.error(f"Invalid score: {evaluation['score']}")
                        evaluation['score'] = 0
                    
                    return evaluation
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    logger.error(f"Raw response: {response_text}")
                    return {
                        "error": "Failed to parse JSON response",
                        "details": str(e),
                        "raw_response": response_text,
                        "score": 0,
                        "max_score": 3,
                        "comment": "Ошибка при разборе ответа системы проверки"
                    }
                except Exception as e:
                    logger.error(f"Unexpected error in response processing: {e}")
                    return {
                        "error": "Unexpected error",
                        "details": str(e),
                        "score": 0,
                        "max_score": 3,
                        "comment": "Неожиданная ошибка при проверке"
                    }
                    
    except aiohttp.ClientError as e:
        logger.error(f"Network error: {e}")
        return {
            "error": "Network error",
            "details": str(e),
            "score": 0,
            "max_score": 3,
            "comment": "Ошибка сети при обращении к системе проверки"
        }
    except Exception as e:
        logger.error(f"Unexpected error in check_task20: {e}")
        return {
            "error": "Unexpected error",
            "details": str(e),
            "score": 0,
            "max_score": 3,
            "comment": "Неожиданная ошибка при проверке"
        }


def evaluate_task20(task_text: str, student_answer: str) -> Dict[str, Any]:
    """
    Синхронная обёртка для проверки задания 20.
    
    Args:
        task_text: Текст задания
        student_answer: Ответ ученика
        
    Returns:
        Dict с результатами проверки
    """
    try:
        # Создаем новый event loop если его нет
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Запускаем асинхронную функцию
        result = loop.run_until_complete(check_task20(task_text, student_answer))
        
        return result
        
    except Exception as e:
        logger.error(f"Error in evaluate_task20: {e}")
        return {
            "error": "Failed to evaluate task",
            "details": str(e),
            "score": 0,
            "max_score": 3,
            "comment": "Ошибка при проверке задания"
        }


# Пример использования для тестирования
if __name__ == "__main__":
    # Пример из методических рекомендаций
    task_example = """
    Используя обществоведческие знания, приведите два аргумента, 
    подтверждающих положительное воздействие средств массовой информации на 
    развитие личности ребёнка, и два аргумента, указывающих на возможное их 
    негативное влияние. (Всего должно быть приведено четыре аргумента. 
    Каждый аргумент должен быть сформулирован как распространённое предложение.)
    """
    
    # Пример ответа с оценкой 3 балла
    answer_example = """
    Положительное воздействие СМИ:
    1) СМИ способствуют расширению кругозора ребёнка, предоставляя доступ к разнообразной 
    информации о мире, что содействует формированию целостной картины мира и развитию 
    познавательных способностей.
    2) Средства массовой информации позволяют ребёнку приобщаться к культурным ценностям 
    общества, что способствует его социализации и формированию культурной идентичности.
    
    Негативное влияние СМИ:
    1) СМИ могут негативно влиять на психическое здоровье ребёнка, так как часто содержат 
    сцены насилия и агрессии, что может приводить к повышению тревожности и формированию 
    агрессивных моделей поведения.
    2) Средства массовой информации нередко прибегают к манипулированию сознанием аудитории, 
    что особенно опасно для детей в силу отсутствия у них критического мышления и жизненного 
    опыта, что может приводить к формированию искаженных представлений о реальности.
    """
    
    result = evaluate_task20(task_example, answer_example)
    print(json.dumps(result, ensure_ascii=False, indent=2))
# plugins/task25/evaluator.py

import logging
import aiohttp
import json
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class Task25Evaluator:
    """Оценщик ответов для задания 25 через YandexGPT API"""
    
    def __init__(self, yandex_gpt_token: str, plugin):
        self.yandex_gpt_token = yandex_gpt_token
        self.plugin = plugin
        self.api_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
        self.model_uri = "gpt://b1gn3df8r5o5qefadhos/yandexgpt/latest"
        
    async def evaluate_answer(
        self,
        task_text: str,
        student_answer: str,
        task_id: str = "unknown"
    ) -> Dict[str, Any]:
        """Оценивает ответ студента через YandexGPT API"""
        try:
            # Создаем промпт для оценки
            prompt = self.plugin.create_evaluation_prompt(task_text, student_answer)
            
            # Подготавливаем запрос к API
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Api-Key {self.yandex_gpt_token}"
            }
            
            payload = {
                "modelUri": self.model_uri,
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.1,  # Низкая температура для более стабильной оценки
                    "maxTokens": 2000
                },
                "messages": [
                    {
                        "role": "system",
                        "text": "Ты эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 25. Оценивай строго по критериям."
                    },
                    {
                        "role": "user",
                        "text": prompt
                    }
                ]
            }
            
            # Выполняем запрос к API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Ошибка API YandexGPT: {response.status} - {error_text}")
                        return {
                            "success": False,
                            "error": f"Ошибка API: {response.status}"
                        }
                    
                    result = await response.json()
                    
            # Извлекаем ответ модели
            gpt_response = result.get("result", {}).get("alternatives", [{}])[0].get("message", {}).get("text", "")
            
            if not gpt_response:
                logger.error("Пустой ответ от YandexGPT")
                return {
                    "success": False,
                    "error": "Получен пустой ответ от модели"
                }
            
            logger.info(f"Ответ YandexGPT для задания {task_id}: {gpt_response[:200]}...")
            
            # Парсим ответ модели
            evaluation = self.plugin.parse_evaluation_response(gpt_response)
            
            # Добавляем дополнительную информацию
            evaluation['task_id'] = task_id
            evaluation['model_response'] = gpt_response
            
            # Валидация результатов
            if evaluation.get("success"):
                scores = evaluation.get("scores", {})
                # Проверяем, что все критерии оценены
                if not all(criterion in scores for criterion in ["25.1", "25.2", "25.3"]):
                    missing = [c for c in ["25.1", "25.2", "25.3"] if c not in scores]
                    logger.warning(f"Отсутствуют оценки для критериев: {missing}")
                    # Устанавливаем 0 для отсутствующих критериев
                    for criterion in missing:
                        scores[criterion] = 0
                    evaluation["scores"] = scores
                    evaluation["total_score"] = sum(scores.values())
            
            return evaluation
            
        except aiohttp.ClientTimeout:
            logger.error("Таймаут при запросе к YandexGPT API")
            return {
                "success": False,
                "error": "Превышено время ожидания ответа от сервера"
            }
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка сети при запросе к YandexGPT: {e}")
            return {
                "success": False,
                "error": "Ошибка сети при обращении к серверу"
            }
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON ответа: {e}")
            return {
                "success": False,
                "error": "Некорректный формат ответа от сервера"
            }
        except Exception as e:
            logger.error(f"Неожиданная ошибка в evaluate_answer: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Неожиданная ошибка: {str(e)}"
            }
    
    def validate_answer_structure(self, answer: str) -> Optional[str]:
        """Проверяет базовую структуру ответа"""
        lines = answer.strip().split('\n')
        
        # Проверяем минимальную длину
        if len(answer.strip()) < 100:
            return "Ответ слишком короткий для задания 25"
        
        # Проверяем наличие структуры (пунктов)
        has_numbering = any(
            line.strip().startswith(('1)', '1.', '1 ', 'а)', 'а.', 'a)')) 
            for line in lines
        )
        
        if not has_numbering and len(lines) < 5:
            return "Ответ должен быть структурирован и содержать три части: обоснование, ответ на вопрос и примеры"
        
        return None
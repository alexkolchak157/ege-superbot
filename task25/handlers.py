class Task25Handler:
    def __init__(self, evaluator):
        self.evaluator = evaluator
        
    async def handle_submission(self, user_id: str, task_data: dict, answer: str):
        """Основная точка входа для обработки ответа"""
        # Валидация входных данных
        # Вызов evaluator для оценки
        # Форматирование результата для пользователя
        
    async def handle_partial_check(self, user_id: str, task_data: dict, 
                                   part: str, text: str):
        """Проверка отдельной части ответа (обоснование/ответ/примеры)"""
        # Позволяет проверить часть до отправки полного ответа
        
    def format_feedback(self, evaluation_result: dict) -> str:
        """Форматирование обратной связи для пользователя"""
        # Человекочитаемое представление оценок
        # Рекомендации по улучшению
        
    def parse_answer_structure(self, answer: str) -> dict:
        """Разбор ответа на составные части"""
        # Извлечение обоснования, ответа, примеров
        # Обработка разных форматов (1), 2), 3) или а), б), в))
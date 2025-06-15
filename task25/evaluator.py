class Task25Evaluator:
    def __init__(self):
        self.criteria_weights = {
            'justification': 2,
            'answer': 1, 
            'examples': 3
        }
        
    def evaluate(self, task_data: dict, answer_parts: dict) -> dict:
        """Главный метод оценки всего ответа"""
        # Координация оценки всех частей
        # Возврат детализированного результата
        
    # === Оценка обоснования (критерий 25.1) ===
    def evaluate_justification(self, text: str, task_context: dict) -> dict:
        """Оценка обоснования (0-2 балла)"""
        
    def check_scientific_basis(self, text: str) -> bool:
        """Проверка опоры на обществоведческие знания"""
        
    def check_causal_links(self, text: str) -> bool:
        """Проверка причинно-следственных связей"""
        
    def count_extended_sentences(self, text: str) -> int:
        """Подсчёт распространённых предложений"""
        
    # === Оценка ответа на вопрос (критерий 25.2) ===
    def evaluate_answer(self, text: str, required_count: int) -> dict:
        """Оценка ответа на вопрос (0-1 балл)"""
        
    def extract_items(self, text: str) -> list:
        """Извлечение названных объектов/элементов"""
        
    def validate_items(self, items: list, task_context: dict) -> tuple:
        """Проверка корректности названных элементов"""
        
    # === Оценка примеров (критерий 25.3) ===
    def evaluate_examples(self, text: str, named_items: list, 
                         task_requirements: dict) -> dict:
        """Оценка примеров (0-3 балла)"""
        
    def extract_examples(self, text: str) -> list:
        """Извлечение примеров из текста"""
        
    def match_examples_to_items(self, examples: list, items: list) -> dict:
        """Сопоставление примеров с названными объектами"""
        
    def check_example_quality(self, example: str, requirements: dict) -> bool:
        """Проверка качества примера (развёрнутость, соответствие)"""
        
    # === Вспомогательные методы ===
    def detect_errors_in_additional_examples(self, examples: list) -> bool:
        """Проверка дополнительных примеров на ошибки"""
        
    def check_contextual_requirements(self, text: str, context: str) -> bool:
        """Проверка контекстуальных требований (например, российский контекст)"""
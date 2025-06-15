class Task25Plugin:
    def __init__(self):
        self.name = "task25"
        self.display_name = "Задание 25"
        self.max_score = 6
        self.evaluator = Task25Evaluator()
        self.handler = Task25Handler(self.evaluator)
        
    def register(self, app):
        """Регистрация роутов и хендлеров"""
        app.add_route('/task25/submit', self.handler.handle_submission)
        app.add_route('/task25/check-part', self.handler.handle_partial_check)
        
    def get_task_info(self) -> dict:
        """Информация о типе задания"""
        return {
            'type': 'task25',
            'name': 'Обоснование и примеры',
            'max_score': 6,
            'parts': ['justification', 'answer', 'examples'],
            'criteria': self.get_criteria_info()
        }
        
    def get_criteria_info(self) -> dict:
        """Описание критериев оценивания"""
        return {
            '25.1': {
                'name': 'Обоснование',
                'max_score': 2,
                'description': 'Корректное обоснование с опорой на обществоведческие знания'
            },
            '25.2': {
                'name': 'Ответ на вопрос',
                'max_score': 1,
                'description': 'Указание требуемого количества объектов'
            },
            '25.3': {
                'name': 'Примеры',
                'max_score': 3,
                'description': 'Развёрнутые примеры, соответствующие требованиям'
            }
        }
        
    def get_example_tasks(self) -> list:
        """Примеры заданий для тестирования"""
        
    def get_evaluation_prompt_template(self) -> str:
        """Шаблон промпта для LLM оценки"""
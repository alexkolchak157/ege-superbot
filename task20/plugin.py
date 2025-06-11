from flask import Blueprint
from .task20_handlers import (
    handle_task20_check,
    handle_task20_bulk_check,
    handle_task20_statistics,
    handle_task20_export
)

# Создаем Blueprint для задания 20
task20_bp = Blueprint('task20', __name__, url_prefix='/api/task20')

# Регистрируем маршруты
task20_bp.route('/check', methods=['POST'])(handle_task20_check)
task20_bp.route('/bulk-check', methods=['POST'])(handle_task20_bulk_check)
task20_bp.route('/statistics', methods=['GET'])(handle_task20_statistics)
task20_bp.route('/export', methods=['POST'])(handle_task20_export)

def init_task20(app):
    """
    Инициализация плагина задания 20
    
    Args:
        app: Flask приложение
    """
    app.register_blueprint(task20_bp)
    app.logger.info("Task 20 plugin initialized")

# Экспортируем для использования в других модулях
__all__ = ['task20_bp', 'init_task20']
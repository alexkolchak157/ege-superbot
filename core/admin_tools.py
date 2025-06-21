"""
Универсальный модуль администратора для всех заданий бота.
Содержит функции статистики, мониторинга и управления.
"""

import logging
import json
import os
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from functools import wraps
import io

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class AdminManager:
    """Менеджер административных функций."""
    
    _instance = None
    _admin_ids: List[int] = []
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AdminManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        self._load_admin_ids()
    
    def _load_admin_ids(self):
        """Загрузка списка администраторов из различных источников."""
        admin_ids = set()
        
        # 1. Загрузка из переменных окружения
        env_admins = os.getenv('BOT_ADMIN_IDS', '')
        if env_admins:
            try:
                for admin_id in env_admins.split(','):
                    admin_id = admin_id.strip()
                    if admin_id:
                        admin_ids.add(int(admin_id))
                logger.info(f"Loaded {len(admin_ids)} admins from environment")
            except ValueError as e:
                logger.warning(f"Invalid admin IDs in environment: {e}")
        
        # 2. Загрузка из общего конфига
        try:
            config_file = os.path.join(os.path.dirname(__file__), 'admin_config.json')
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    for admin_id in config.get('admin_ids', []):
                        admin_ids.add(int(admin_id))
                logger.info(f"Loaded admins from config file")
        except Exception as e:
            logger.error(f"Error loading admin config: {e}")
        
        # 3. Загрузка специфичных админов для модулей
        for env_var in ['TASK24_ADMIN_IDS', 'TASK19_ADMIN_IDS', 'TASK20_ADMIN_IDS']:
            module_admins = os.getenv(env_var, '')
            if module_admins:
                try:
                    for admin_id in module_admins.split(','):
                        admin_id = admin_id.strip()
                        if admin_id:
                            admin_ids.add(int(admin_id))
                except ValueError:
                    pass
        
        self._admin_ids = list(admin_ids)
        
        if not self._admin_ids:
            logger.warning("No admin IDs configured - admin functions disabled")
            # Создаем пример конфига
            example_config = {
                "admin_ids": [],
                "comment": "Add Telegram user IDs of bot administrators here"
            }
            try:
                with open(config_file, 'w') as f:
                    json.dump(example_config, f, indent=4)
                logger.info(f"Created example admin config: {config_file}")
            except:
                pass
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором."""
        return user_id in self._admin_ids
    
    def add_admin(self, user_id: int):
        """Добавление администратора (runtime only)."""
        if user_id not in self._admin_ids:
            self._admin_ids.append(user_id)
    
    def remove_admin(self, user_id: int):
        """Удаление администратора (runtime only)."""
        if user_id in self._admin_ids:
            self._admin_ids.remove(user_id)
    
    def get_admin_list(self) -> List[int]:
        """Получение списка администраторов."""
        return self._admin_ids.copy()


# Глобальный экземпляр
admin_manager = AdminManager()


def admin_only(func: Callable) -> Callable:
    """Декоратор для функций, доступных только администраторам."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else None
        
        if not user_id or not admin_manager.is_admin(user_id):
            if update.callback_query:
                await update.callback_query.answer(
                    "❌ Эта функция доступна только администраторам", 
                    show_alert=True
                )
            else:
                await update.message.reply_text(
                    "❌ Эта функция доступна только администраторам"
                )
            return ConversationHandler.END
            
        return await func(update, context, *args, **kwargs)
    return wrapper


class AdminStats:
    """Класс для сбора и анализа статистики."""
    
    @staticmethod
    async def get_global_stats(application) -> Dict[str, Any]:
        """Получение глобальной статистики по всем пользователям."""
        stats = {
            'total_users': 0,
            'active_users': 0,
            'total_attempts': 0,
            'by_module': defaultdict(lambda: {
                'users': 0,
                'attempts': 0,
                'avg_score': 0
            }),
            'daily_activity': defaultdict(int),
            'hourly_activity': defaultdict(int),
            'top_users': []
        }
        
        # Анализируем данные всех пользователей
        for user_id, user_data in application.user_data.items():
            if not isinstance(user_data, dict):
                continue
                
            stats['total_users'] += 1
            
            # Проверяем активность за последние 30 дней
            was_active = False
            
            # Task24 статистика
            if 'practiced_topics' in user_data:
                stats['by_module']['task24']['users'] += 1
                scores_history = user_data.get('scores_history', [])
                
                if scores_history:
                    was_active = True
                    stats['by_module']['task24']['attempts'] += len(scores_history)
                    avg = sum(s['total'] for s in scores_history) / len(scores_history)
                    stats['by_module']['task24']['avg_score'] = avg
                    
                    # Анализ по дням
                    for score in scores_history:
                        if timestamp := score.get('timestamp'):
                            try:
                                dt = datetime.fromisoformat(timestamp)
                                stats['daily_activity'][dt.date()] += 1
                                stats['hourly_activity'][dt.hour] += 1
                            except:
                                pass
            
            # Test Part статистика
            if 'mistakes' in user_data or 'correct_answers' in user_data:
                stats['by_module']['test_part']['users'] += 1
                was_active = True
            
            # Task19 статистика  
            if 'task19_results' in user_data:
                stats['by_module']['task19']['users'] += 1
                results = user_data.get('task19_results', [])
                if results:
                    was_active = True
                    stats['by_module']['task19']['attempts'] += len(results)
                    avg = sum(r['score'] for r in results) / len(results)
                    stats['by_module']['task19']['avg_score'] = avg
            
            # Task20 статистика
            if 'practice_stats' in user_data:
                stats['by_module']['task20']['users'] += 1
                practice_stats = user_data.get('practice_stats', {})
                total_attempts = sum(s.get('attempts', 0) for s in practice_stats.values())
                if total_attempts > 0:
                    was_active = True
                    stats['by_module']['task20']['attempts'] += total_attempts
            
            # Task25 статистика
            if 'task25_stats' in user_data:
                stats['by_module']['task25']['users'] += 1
                was_active = True
            
            if was_active:
                stats['active_users'] += 1
            
            # Подсчет общих попыток
            stats['total_attempts'] += len(user_data.get('scores_history', []))
            stats['total_attempts'] += len(user_data.get('task19_results', []))
        
        return stats
    
    @staticmethod
    async def get_user_detailed_stats(user_id: int, user_data: Dict) -> Dict[str, Any]:
        """Детальная статистика конкретного пользователя."""
        stats = {
            'user_id': user_id,
            'modules': {},
            'total_time': 0,
            'last_activity': None,
            'achievements': []
        }
        
        # Task24
        if 'practiced_topics' in user_data:
            stats['modules']['task24'] = {
                'practiced_topics': len(user_data.get('practiced_topics', set())),
                'total_attempts': len(user_data.get('scores_history', [])),
                'average_score': 0,
                'time_spent': user_data.get('total_time_minutes', 0)
            }
            
            if scores := user_data.get('scores_history', []):
                stats['modules']['task24']['average_score'] = \
                    sum(s['total'] for s in scores) / len(scores)
        
        # Другие модули...
        
        return stats
    
    @staticmethod
    def format_activity_graph(daily_activity: Dict, days: int = 14) -> str:
        """Форматирование графика активности."""
        if not daily_activity:
            return "Нет данных об активности"
        
        sorted_days = sorted(daily_activity.keys(), reverse=True)[:days]
        
        lines = []
        max_activity = max(daily_activity.values()) if daily_activity else 1
        
        for date in sorted_days:
            activity = daily_activity[date]
            bar_length = int((activity / max_activity) * 20)
            bar = "▓" * bar_length + "░" * (20 - bar_length)
            lines.append(f"<code>{date.strftime('%d.%m')} {bar} {activity}</code>")
        
        return "\n".join(lines)


class AdminKeyboards:
    """Клавиатуры для админских функций."""
    
    @staticmethod
    def main_admin_menu() -> InlineKeyboardMarkup:
        """Главное админское меню."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Общая статистика", callback_data="admin:global_stats")],
            [InlineKeyboardButton("👥 Пользователи", callback_data="admin:users_list")],
            [InlineKeyboardButton("📈 Активность", callback_data="admin:activity")],
            [InlineKeyboardButton("📤 Экспорт данных", callback_data="admin:export")],
            [InlineKeyboardButton("🔍 Поиск пользователя", callback_data="admin:search_user")],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="admin:settings")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:back")]
        ])
    
    @staticmethod
    def stats_menu() -> InlineKeyboardMarkup:
        """Меню статистики."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 По модулям", callback_data="admin:stats_modules")],
            [InlineKeyboardButton("📅 По дням", callback_data="admin:stats_daily")],
            [InlineKeyboardButton("🕐 По часам", callback_data="admin:stats_hourly")],
            [InlineKeyboardButton("🏆 Топ пользователей", callback_data="admin:stats_top")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])
    
    @staticmethod
    def user_actions(user_id: int) -> InlineKeyboardMarkup:
        """Действия с пользователем."""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Статистика", callback_data=f"admin:user_stats:{user_id}")],
            [InlineKeyboardButton("📝 История", callback_data=f"admin:user_history:{user_id}")],
            [InlineKeyboardButton("🔄 Сбросить прогресс", callback_data=f"admin:user_reset:{user_id}")],
            [InlineKeyboardButton("💬 Отправить сообщение", callback_data=f"admin:user_message:{user_id}")],
            [InlineKeyboardButton("⬅️ К списку", callback_data="admin:users_list")]
        ])


# Обработчики админских команд

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главная админская панель."""
    query = update.callback_query
    if query:
        await query.answer()
    
    text = (
        "🔧 <b>Панель администратора</b>\n\n"
        "Выберите раздел для управления ботом:"
    )
    
    kb = AdminKeyboards.main_admin_menu()
    
    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def global_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ глобальной статистики."""
    query = update.callback_query
    await query.answer("Загрузка статистики...")
    
    stats = await AdminStats.get_global_stats(context.application)
    
    text = (
        "📊 <b>Глобальная статистика бота</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🎯 Активных (30 дней): {stats['active_users']}\n"
        f"📝 Всего попыток: {stats['total_attempts']}\n\n"
        "<b>По модулям:</b>\n"
    )
    
    for module, data in stats['by_module'].items():
        if data['users'] > 0:
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }
            name = module_names.get(module, module)
            text += (
                f"\n{name}:\n"
                f"  • Пользователей: {data['users']}\n"
                f"  • Попыток: {data['attempts']}\n"
            )
            if data.get('avg_score'):
                text += f"  • Средний балл: {data['avg_score']:.2f}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Подробная статистика", callback_data="admin:stats_menu")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def activity_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """График активности пользователей."""
    query = update.callback_query
    await query.answer()
    
    stats = await AdminStats.get_global_stats(context.application)
    
    text = "📈 <b>Активность по дням (последние 14 дней)</b>\n\n"
    text += AdminStats.format_activity_graph(stats['daily_activity'], days=14)
    
    # Статистика по дням недели
    weekday_stats = defaultdict(int)
    for date, count in stats['daily_activity'].items():
        weekday = date.strftime('%A')
        weekday_stats[weekday] += count
    
    if weekday_stats:
        text += "\n\n<b>По дням недели:</b>\n"
        for day, count in sorted(weekday_stats.items(), key=lambda x: x[1], reverse=True):
            text += f"{day}: {count} действий\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🕐 По часам", callback_data="admin:stats_hourly")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def export_all_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт всех данных в JSON."""
    query = update.callback_query
    await query.answer("Подготовка данных...")
    
    export_data = {
        'export_date': datetime.now().isoformat(),
        'bot_name': context.bot.username,
        'statistics': await AdminStats.get_global_stats(context.application),
        'users': {}
    }
    
    # Собираем данные пользователей
    for user_id, user_data in context.application.user_data.items():
        if isinstance(user_data, dict) and user_data:  # Только непустые словари
            export_data['users'][str(user_id)] = {
                'data': dict(user_data),  # Конвертируем в обычный dict
                'stats': await AdminStats.get_user_detailed_stats(user_id, user_data)
            }
    
    # Создаем файл
    file_buffer = io.BytesIO(
        json.dumps(export_data, indent=2, ensure_ascii=False, default=str).encode('utf-8')
    )
    file_buffer.name = f"bot_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    # Удаляем старое сообщение
    try:
        await query.message.delete()
    except:
        pass
    
    # Отправляем файл
    await query.message.reply_document(
        document=file_buffer,
        filename=file_buffer.name,
        caption=(
            f"📤 <b>Полный экспорт данных</b>\n"
            f"Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"Пользователей: {len(export_data['users'])}\n\n"
            f"⚠️ Файл содержит персональные данные!"
        ),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик админских callback'ов."""
    query = update.callback_query
    await query.answer()
    
    data = query.data.split(":")
    action = data[1] if len(data) > 1 else ""
    
    if action == "main":
        return await admin_panel(update, context)
    elif action == "global_stats":
        return await global_stats(update, context)
    elif action == "activity":
        return await activity_stats(update, context)
    elif action == "export":
        return await export_all_data(update, context)
    elif action == "stats_menu":
        # Показываем меню статистики
        text = "📊 <b>Выберите тип статистики</b>"
        kb = AdminKeyboards.stats_menu()
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


# Функции для интеграции с модулями

def get_admin_keyboard_extension(user_id: int) -> List[List[InlineKeyboardButton]]:
    """Возвращает дополнительные кнопки для админов в обычных меню."""
    if not admin_manager.is_admin(user_id):
        return []
    
    return [
        [InlineKeyboardButton("🔧 Админ-панель", callback_data="admin:main")]
    ]


def register_admin_handlers(app):
    """Регистрация админских обработчиков в приложении."""
    from telegram.ext import CallbackQueryHandler, CommandHandler
    
    # Команда /admin
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Callback обработчики
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^admin:"))
    
    logger.info("Admin handlers registered")


# Экспорт основных компонентов
__all__ = [
    'admin_manager',
    'admin_only',
    'AdminStats',
    'AdminKeyboards',
    'register_admin_handlers',
    'get_admin_keyboard_extension'
]

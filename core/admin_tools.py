"""
Универсальный модуль администратора для всех заданий бота.
Содержит функции статистики, мониторинга и управления.
Исправлена валидация admin IDs и добавлено логирование попыток доступа.
"""

import logging
import json
import os
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from functools import wraps
import io
from core.types import UserID, TaskType, EvaluationResult, CallbackData
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, CallbackQueryHandler
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class AdminManager:
    """Менеджер административных функций с безопасной валидацией."""
    
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
        self._failed_attempts = defaultdict(list)  # Для логирования попыток взлома
    
    def _validate_admin_id(self, admin_id_str: str) -> Optional[int]:
        """
        Безопасная валидация и преобразование admin ID.
        Возвращает int если валидно, иначе None.
        """
        try:
            admin_id = int(admin_id_str.strip())
            # Проверяем что ID положительный и в разумных пределах
            if 0 < admin_id < 10**15:  # Telegram user IDs обычно меньше
                return admin_id
            else:
                logger.warning(f"Admin ID вне допустимого диапазона: {admin_id}")
                return None
        except (ValueError, AttributeError) as e:
            logger.warning(f"Невалидный admin ID: {admin_id_str} - {e}")
            return None
    
    def _load_admin_ids(self):
        """Загрузка списка администраторов из различных источников с валидацией."""
        admin_ids = set()
        
        # 1. Загрузка из переменных окружения с валидацией
        env_vars = [
            'BOT_ADMIN_IDS',
            'TASK24_ADMIN_IDS', 
            'TASK19_ADMIN_IDS', 
            'TASK20_ADMIN_IDS',
            'TASK25_ADMIN_IDS'
        ]
        
        for env_var in env_vars:
            env_admins = os.getenv(env_var, '')
            if env_admins:
                logger.info(f"Загрузка админов из {env_var}")
                for admin_id_str in env_admins.split(','):
                    if admin_id_str.strip():
                        admin_id = self._validate_admin_id(admin_id_str)
                        if admin_id:
                            admin_ids.add(admin_id)
                            logger.info(f"Добавлен админ ID: {admin_id}")
                        else:
                            logger.error(f"Отклонен невалидный admin ID из {env_var}: {admin_id_str}")
        
        # 2. Загрузка из JSON-файлов конфигурации с валидацией
        config_files = [
            os.path.join(os.path.dirname(__file__), 'admin_config.json'),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), 'task24', 'admin_config.json'),
        ]
        
        for cfg_path in config_files:
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        
                    # Валидация структуры JSON
                    if not isinstance(config, dict):
                        logger.error(f"Неверная структура конфига {cfg_path}: ожидался dict")
                        continue
                        
                    admin_list = config.get('admin_ids', [])
                    if not isinstance(admin_list, list):
                        logger.error(f"admin_ids должен быть списком в {cfg_path}")
                        continue
                    
                    for admin_id_value in admin_list:
                        # Поддерживаем как числа так и строки в JSON
                        admin_id = self._validate_admin_id(str(admin_id_value))
                        if admin_id:
                            admin_ids.add(admin_id)
                            logger.info(f"Добавлен админ ID из {cfg_path}: {admin_id}")
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Ошибка парсинга JSON {cfg_path}: {e}")
                except Exception as e:
                    logger.error(f"Ошибка загрузки конфига {cfg_path}: {e}")
        
        self._admin_ids = sorted(list(admin_ids))  # Сортируем для консистентности
        
        if not self._admin_ids:
            logger.warning("⚠️ Не настроены администраторы - админ функции отключены")
            # Создаем пример конфига
            example_config = {
                "admin_ids": [],
                "comment": "Добавьте Telegram user ID администраторов (числа)"
            }
            
            config_file = os.path.join(os.path.dirname(__file__), 'admin_config.json')
            if not os.path.exists(config_file):
                try:
                    with open(config_file, 'w') as f:
                        json.dump(example_config, f, indent=4)
                    logger.info(f"Создан пример конфига админов: {config_file}")
                except Exception as e:
                    logger.error(f"Не удалось создать пример конфига: {e}")
        else:
            logger.info(f"✅ Загружено администраторов: {len(self._admin_ids)}")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором."""
        if not isinstance(user_id, int):
            logger.warning(f"is_admin вызван с невалидным типом: {type(user_id)}")
            return False
            
        is_admin = user_id in self._admin_ids
        
        # Логируем попытки доступа не-админов к админским функциям
        if not is_admin:
            self._log_failed_attempt(user_id)
            
        return is_admin
    
    def _log_failed_attempt(self, user_id: int):
        """Логирование неудачных попыток доступа."""
        now = datetime.now(timezone.utc)
        self._failed_attempts[user_id].append(now)
        
        # Оставляем только попытки за последний час
        hour_ago = now - timedelta(hours=1)
        self._failed_attempts[user_id] = [
            t for t in self._failed_attempts[user_id] if t > hour_ago
        ]
        
        # Предупреждение при подозрительной активности
        recent_attempts = len(self._failed_attempts[user_id])
        if recent_attempts >= 3:
            logger.warning(
                f"⚠️ Подозрительная активность: user {user_id} "
                f"пытался получить доступ к админ функциям {recent_attempts} раз за час"
            )
    
    def add_admin(self, user_id: int) -> bool:
        """Добавление администратора (runtime only)."""
        if not isinstance(user_id, int) or user_id <= 0:
            logger.error(f"Попытка добавить невалидный admin ID: {user_id}")
            return False
            
        if user_id not in self._admin_ids:
            self._admin_ids.append(user_id)
            self._admin_ids.sort()
            logger.info(f"Администратор {user_id} добавлен (runtime)")
            return True
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Удаление администратора (runtime only)."""
        if user_id in self._admin_ids:
            self._admin_ids.remove(user_id)
            logger.info(f"Администратор {user_id} удален (runtime)")
            return True
        return False
    
    def get_admin_list(self) -> List[int]:
        """Получение списка администраторов."""
        return self._admin_ids.copy()
    
    def get_security_report(self) -> Dict[str, Any]:
        """Отчет о безопасности для супер-админа."""
        return {
            'total_admins': len(self._admin_ids),
            'failed_attempts': {
                user_id: len(attempts) 
                for user_id, attempts in self._failed_attempts.items()
            },
            'suspicious_users': [
                user_id for user_id, attempts in self._failed_attempts.items()
                if len(attempts) >= 3
            ]
        }


# Глобальный экземпляр
admin_manager = AdminManager()


def admin_only(func: Callable) -> Callable:
    """Декоратор для функций, доступных только администраторам."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            logger.warning("admin_only: не удалось определить пользователя")
            return ConversationHandler.END
            
        user_id = user.id
        username = user.username or "NoUsername"
        
        if not admin_manager.is_admin(user_id):
            logger.warning(
                f"❌ Попытка доступа к админ функции: "
                f"user_id={user_id}, username=@{username}, "
                f"function={func.__name__}"
            )
            
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
        
        # Логируем успешное использование админских функций
        logger.info(
            f"✅ Админ {user_id} (@{username}) использует {func.__name__}"
        )
            
        return await func(update, context, *args, **kwargs)
    return wrapper


class AdminStats:
    """Класс для сбора и анализа статистики."""
    
    @staticmethod
    async def get_global_stats(app) -> Dict[str, Any]:
        """Получение глобальной статистики бота."""
        from core import db
        
        stats = {
            'total_users': 0,
            'active_users': 0,  # Активные за последние 30 дней
            'total_attempts': 0,
            'by_module': defaultdict(lambda: {
                'users': 0,
                'attempts': 0,
                'avg_score': 0
            }),
            'daily_activity': defaultdict(int)
        }
        
        try:
            # Получаем всех пользователей из БД
            conn = await db.get_db()
            cursor = await conn.execute(
                "SELECT user_id, last_activity_date FROM users"
            )
            users = await cursor.fetchall()
            
            stats['total_users'] = len(users)
            
            # Считаем активных за последние 30 дней
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            for user_row in users:
                if user_row['last_activity_date']:
                    try:
                        last_activity = datetime.fromisoformat(
                            str(user_row['last_activity_date'])
                        )
                        if last_activity > thirty_days_ago:
                            stats['active_users'] += 1
                    except:
                        pass
            
            # Статистика по модулям из bot_data
            bot_data = app.bot_data
            
            for user_id, user_data in bot_data.items():
                if not isinstance(user_data, dict):
                    continue
                
                was_active = False
                
                # Task24 статистика
                if 'practiced_topics' in user_data:
                    stats['by_module']['task24']['users'] += 1
                    was_active = True
                    
                    # Подсчет попыток
                    if 'scores_history' in user_data:
                        attempts = len(user_data['scores_history'])
                        stats['by_module']['task24']['attempts'] += attempts
                        
                        # Средний балл
                        if attempts > 0:
                            total_score = sum(
                                s.get('total', 0) 
                                for s in user_data['scores_history']
                            )
                            stats['by_module']['task24']['avg_score'] = total_score / attempts
                
                # Test_part статистика
                if any(key.startswith('test_') for key in user_data.keys()):
                    stats['by_module']['test_part']['users'] += 1
                    was_active = True
                
                # Task19 статистика
                if 'task19_results' in user_data:
                    stats['by_module']['task19']['users'] += 1
                    was_active = True
                    results = user_data.get('task19_results', [])
                    stats['by_module']['task19']['attempts'] += len(results)
                    
                    if results:
                        avg = sum(r.get('score', 0) for r in results) / len(results)
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
                    stats['total_attempts'] += len(user_data.get('scores_history', []))
                    stats['total_attempts'] += len(user_data.get('task19_results', []))
            
        except Exception as e:
            logger.error(f"Ошибка при сборе статистики: {e}")
        
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
        
        # Добавить другие модули по аналогии...
        
        return stats
    
    @staticmethod
    def format_activity_graph(daily_activity: Dict, days: int = 14) -> str:
        """Форматирование графика активности."""
        if not daily_activity:
            return "Нет данных об активности"
        
        # Сортируем даты в обратном порядке (новые сверху)
        sorted_days = sorted(daily_activity.keys(), reverse=True)[:days]
        
        if not sorted_days:
            return "Нет данных об активности"
        
        lines = []
        max_activity = max(daily_activity.values()) if daily_activity else 1
        
        for date in sorted_days:
            activity = daily_activity.get(date, 0)
            bar_length = int((activity / max_activity) * 20) if max_activity > 0 else 0
            bar = "▓" * bar_length + "░" * (20 - bar_length)
            lines.append(f"<code>{date.strftime('%d.%m')} {bar} {activity}</code>")
        
        return "\n".join(lines)


class AdminKeyboards:
    """Клавиатуры для админских функций."""
    
    @staticmethod
    def main_admin_menu() -> InlineKeyboardMarkup:
        """Главное админское меню."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Статистика", callback_data="admin:stats"),
                InlineKeyboardButton("👥 Пользователи", callback_data="admin:users")
            ],
            [
                InlineKeyboardButton("📨 Рассылка", callback_data="admin:broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin:settings")
            ],
            [
                InlineKeyboardButton("🔒 Безопасность", callback_data="admin:security"),
                InlineKeyboardButton("📤 Экспорт", callback_data="admin:export")
            ],
            [InlineKeyboardButton("❌ Закрыть", callback_data="admin:close")]
        ])
    
    @staticmethod
    def stats_menu() -> InlineKeyboardMarkup:
        """Меню статистики."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🌍 Глобальная", callback_data="admin:global_stats"),
                InlineKeyboardButton("📈 Активность", callback_data="admin:activity_stats")
            ],
            [
                InlineKeyboardButton("📚 По модулям", callback_data="admin:module_stats"),
                InlineKeyboardButton("🏆 Топ юзеров", callback_data="admin:top_users")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])


# === Обработчики команд ===

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главная админ панель."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user = update.effective_user
    text = (
        f"🔧 <b>Панель администратора</b>\n\n"
        f"Добро пожаловать, {user.first_name}!\n"
        f"Выберите раздел для управления ботом:"
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
async def security_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отчет о безопасности."""
    query = update.callback_query
    await query.answer()
    
    report = admin_manager.get_security_report()
    
    text = (
        "🔒 <b>Отчет о безопасности</b>\n\n"
        f"👮 Администраторов: {report['total_admins']}\n\n"
    )
    
    if report['suspicious_users']:
        text += "⚠️ <b>Подозрительная активность:</b>\n"
        for user_id in report['suspicious_users']:
            attempts = report['failed_attempts'].get(user_id, 0)
            text += f"  • User {user_id}: {attempts} попыток за час\n"
    else:
        text += "✅ Подозрительной активности не обнаружено\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:security")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


def get_admin_keyboard_extension(user_id: int) -> List[List[InlineKeyboardButton]]:
    """Возвращает дополнительные кнопки для админов."""
    if admin_manager.is_admin(user_id):
        return [[InlineKeyboardButton("🛠 Админ", callback_data="admin:main")]]
    return []


def register_admin_handlers(app):
    """Регистрация админских обработчиков."""
    # Команда /admin
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # Callback обработчики
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin:main$"))
    app.add_handler(CallbackQueryHandler(global_stats, pattern="^admin:global_stats$"))
    app.add_handler(CallbackQueryHandler(security_report, pattern="^admin:security$"))
    
    # Закрытие панели
    async def close_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.callback_query.answer()
        await update.callback_query.delete_message()
    
    app.add_handler(CallbackQueryHandler(close_admin_panel, pattern="^admin:close$"))
    
    logger.info("Админские обработчики зарегистрированы")
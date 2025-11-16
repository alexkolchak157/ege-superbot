"""
Сервис для отправки уведомлений ученикам о домашних заданиях.
"""

import logging
from datetime import datetime
from typing import List, Optional
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)


async def notify_students_about_homework(
    bot: Bot,
    student_ids: List[int],
    homework_title: str,
    teacher_name: str,
    deadline: Optional[datetime] = None,
    questions_count: int = 0
) -> dict:
    """
    Отправляет уведомления ученикам о новом домашнем задании.

    Args:
        bot: Telegram Bot instance
        student_ids: Список ID учеников для уведомления
        homework_title: Название домашнего задания
        teacher_name: Имя учителя
        deadline: Дедлайн выполнения (опционально)
        questions_count: Количество заданий

    Returns:
        Dict с результатами отправки: {'success': int, 'failed': int, 'failed_ids': List[int]}
    """
    success_count = 0
    failed_count = 0
    failed_ids = []

    # Формируем текст уведомления
    text = (
        f"📝 <b>Новое домашнее задание!</b>\n\n"
        f"👨‍🏫 <b>Учитель:</b> {teacher_name}\n"
        f"📋 <b>Название:</b> {homework_title}\n"
    )

    if questions_count > 0:
        text += f"📊 <b>Заданий:</b> {questions_count}\n"

    if deadline:
        deadline_str = deadline.strftime("%d.%m.%Y %H:%M")
        text += f"⏰ <b>Срок сдачи:</b> {deadline_str}\n"

    text += (
        "\n"
        "💡 Приступайте к выполнению как можно скорее!\n"
        "Посмотреть задание можно в разделе 'Мои задания'."
    )

    # Отправляем каждому ученику
    for student_id in student_ids:
        try:
            await bot.send_message(
                chat_id=student_id,
                text=text,
                parse_mode='HTML'
            )
            success_count += 1
            logger.info(f"✅ Notification sent to student {student_id}")

        except TelegramError as e:
            failed_count += 1
            failed_ids.append(student_id)
            logger.warning(f"❌ Failed to send notification to student {student_id}: {e}")

        except Exception as e:
            failed_count += 1
            failed_ids.append(student_id)
            logger.error(f"❌ Unexpected error sending notification to student {student_id}: {e}")

    result = {
        'success': success_count,
        'failed': failed_count,
        'failed_ids': failed_ids
    }

    logger.info(f"Notification results: {success_count} success, {failed_count} failed out of {len(student_ids)} total")

    return result


async def send_deadline_reminder(
    bot: Bot,
    student_id: int,
    homework_title: str,
    deadline: datetime,
    hours_left: int
) -> bool:
    """
    Отправляет напоминание о приближающемся дедлайне.

    Args:
        bot: Telegram Bot instance
        student_id: ID ученика
        homework_title: Название задания
        deadline: Дедлайн
        hours_left: Сколько часов осталось

    Returns:
        True если отправлено успешно
    """
    try:
        deadline_str = deadline.strftime("%d.%m.%Y %H:%M")

        if hours_left <= 1:
            urgency = "🔴 СРОЧНО!"
            time_text = "менее часа"
        elif hours_left <= 24:
            urgency = "⚠️ Важно!"
            time_text = f"{hours_left} ч."
        else:
            urgency = "📌 Напоминание"
            days_left = hours_left // 24
            time_text = f"{days_left} дн."

        text = (
            f"{urgency}\n\n"
            f"⏰ <b>Приближается дедлайн!</b>\n\n"
            f"📋 <b>Задание:</b> {homework_title}\n"
            f"⏱ <b>Осталось:</b> {time_text}\n"
            f"📅 <b>Срок:</b> {deadline_str}\n\n"
            "💪 Поторопитесь завершить задание!"
        )

        await bot.send_message(
            chat_id=student_id,
            text=text,
            parse_mode='HTML'
        )

        logger.info(f"✅ Deadline reminder sent to student {student_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send deadline reminder to student {student_id}: {e}")
        return False

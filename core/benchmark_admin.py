"""
core/benchmark_admin.py
Админ-команда /benchmark для запуска тестов оценщиков из Telegram.

Использование:
    /benchmark task25        — прогнать бенчмарк для task25
    /benchmark all           — прогнать все задания
    /benchmark task19 t19_001 — прогнать конкретный кейс
"""

import logging
from telegram import Update
from telegram.ext import ContextTypes

from core.admin_tools import admin_only
from core.benchmark import (
    run_benchmark,
    export_mismatches_jsonl,
    save_report_json,
    EVALUATORS,
)

logger = logging.getLogger(__name__)


@admin_only
async def cmd_benchmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /benchmark."""
    args = context.args or []

    if not args:
        available = ", ".join(EVALUATORS.keys())
        await update.message.reply_text(
            f"<b>Бенчмарк AI-оценщиков</b>\n\n"
            f"Использование:\n"
            f"<code>/benchmark task25</code> — прогнать task25\n"
            f"<code>/benchmark all</code> — прогнать все\n"
            f"<code>/benchmark task19 t19_001</code> — конкретный кейс\n\n"
            f"Доступные задания: {available}",
            parse_mode="HTML",
        )
        return

    target = args[0].lower()
    case_ids = args[1:] if len(args) > 1 else None

    if target == "all":
        task_types = list(EVALUATORS.keys())
    elif target in EVALUATORS:
        task_types = [target]
    else:
        await update.message.reply_text(
            f"Неизвестное задание: {target}\n"
            f"Доступные: {', '.join(EVALUATORS.keys())}, all"
        )
        return

    msg = await update.message.reply_text("Запускаю бенчмарк... Это может занять несколько минут.")

    results = []
    for task_type in task_types:
        try:
            report = await run_benchmark(
                task_type=task_type,
                case_ids=case_ids,
            )
            results.append(report)
        except Exception as e:
            logger.error(f"Benchmark error for {task_type}: {e}", exc_info=True)
            results.append(None)

    # Формируем ответ
    lines = ["<b>Результаты бенчмарка</b>\n"]

    for i, task_type in enumerate(task_types):
        report = results[i]
        if report is None:
            lines.append(f"<b>{task_type}</b>: ошибка выполнения")
            continue

        if report.total_cases == 0:
            lines.append(f"<b>{task_type}</b>: нет тестовых кейсов")
            continue

        status = "OK" if report.accuracy == 100 else f"{report.accuracy:.0f}%"
        lines.append(
            f"<b>{task_type}</b>: "
            f"{report.exact_matches}/{report.total_cases} [{status}], "
            f"ср. ошибка: {report.avg_diff:.1f}"
        )

        if report.mismatches:
            for m in report.mismatches[:5]:  # Ограничиваем 5 расхождениями
                diffs = ", ".join(
                    f"{k}: {m.expected_scores.get(k, '?')}→{m.actual_scores.get(k, '?')}"
                    for k, d in m.criteria_diffs.items() if d != 0
                )
                lines.append(
                    f"  <code>[{m.case_id}]</code> {m.topic_title[:30]}: "
                    f"{m.expected_total}→{m.actual_total} ({diffs})"
                )
            if len(report.mismatches) > 5:
                lines.append(f"  ... и ещё {len(report.mismatches) - 5} расхождений")

        # Экспортируем расхождения если есть
        if report.mismatches:
            try:
                path = export_mismatches_jsonl(report)
                lines.append(f"  Расхождения: <code>{path}</code>")
            except Exception:
                pass

        # Сохраняем отчёт
        try:
            path = save_report_json(report)
            lines.append(f"  Отчёт: <code>{path}</code>")
        except Exception:
            pass

    await msg.edit_text("\n".join(lines), parse_mode="HTML")


def register_benchmark_handlers(app):
    """Регистрация обработчиков бенчмарка."""
    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler("benchmark", cmd_benchmark))
    logger.info("Benchmark admin handler registered")

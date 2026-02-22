#!/usr/bin/env python3
"""
CLI-утилита для массового тестирования AI-оценщиков ЕГЭ.

Использование:
    # Прогнать бенчмарк для task25
    python benchmark_runner.py --task task25

    # Прогнать все задания
    python benchmark_runner.py --all

    # Прогнать конкретные кейсы
    python benchmark_runner.py --task task19 --case t19_001 --case t19_002

    # Экспортировать расхождения для дообучения
    python benchmark_runner.py --task task25 --export

    # Сохранить полный отчёт в JSON
    python benchmark_runner.py --all --save-report
"""

import argparse
import asyncio
import logging
import sys
import os

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.benchmark import (
    run_benchmark,
    load_benchmark_cases,
    export_mismatches_jsonl,
    save_report_json,
    EVALUATORS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark_runner")


async def main():
    parser = argparse.ArgumentParser(
        description="Бенчмарк AI-оценщиков ЕГЭ по обществознанию"
    )
    parser.add_argument(
        "--task", "-t",
        choices=list(EVALUATORS.keys()),
        help="Тип задания для тестирования",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Прогнать все задания",
    )
    parser.add_argument(
        "--case", "-c",
        action="append",
        help="ID конкретного кейса (можно указать несколько раз)",
    )
    parser.add_argument(
        "--export", "-e",
        action="store_true",
        help="Экспортировать расхождения в JSONL для дообучения",
    )
    parser.add_argument(
        "--save-report", "-s",
        action="store_true",
        help="Сохранить полный отчёт в JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Подробный вывод (включая фидбек AI)",
    )

    args = parser.parse_args()

    if not args.task and not args.all:
        parser.error("Укажите --task TASK_TYPE или --all")

    task_types = list(EVALUATORS.keys()) if args.all else [args.task]

    all_reports = []

    for task_type in task_types:
        cases = load_benchmark_cases(task_type)
        if not cases:
            logger.warning(f"Нет кейсов для {task_type}, пропускаем")
            continue

        print(f"\n{'='*60}")
        print(f"  Запуск бенчмарка: {task_type} ({len(cases)} кейсов)")
        print(f"{'='*60}")

        report = await run_benchmark(
            task_type=task_type,
            case_ids=args.case,
        )

        print(f"\n{report.summary()}")

        if args.verbose and report.mismatches:
            print("\n--- Подробности расхождений ---")
            for m in report.mismatches:
                print(f"\n[{m.case_id}] {m.topic_title}")
                print(f"  Ожидание: {m.expected_scores} = {m.expected_total}")
                print(f"  Факт:     {m.actual_scores} = {m.actual_total}")
                if m.notes:
                    print(f"  Заметка:  {m.notes}")
                if m.ai_feedback:
                    # Обрезаем фидбек для удобства чтения
                    fb = m.ai_feedback[:300]
                    print(f"  Фидбек AI: {fb}...")

        if args.export and report.mismatches:
            path = export_mismatches_jsonl(report)
            print(f"\nРасхождения экспортированы: {path}")

        if args.save_report:
            path = save_report_json(report)
            print(f"Отчёт сохранён: {path}")

        all_reports.append(report)

    # Итоговая сводка
    if len(all_reports) > 1:
        print(f"\n{'='*60}")
        print("  ИТОГО")
        print(f"{'='*60}")
        total_cases = sum(r.total_cases for r in all_reports)
        total_matches = sum(r.exact_matches for r in all_reports)
        total_mismatches = sum(len(r.mismatches) for r in all_reports)
        accuracy = (total_matches / total_cases * 100) if total_cases else 0

        for r in all_reports:
            status = "OK" if r.accuracy == 100 else f"{r.accuracy:.0f}%"
            print(f"  {r.task_type}: {r.exact_matches}/{r.total_cases} [{status}]")

        print(f"\n  Всего: {total_matches}/{total_cases} ({accuracy:.0f}%)")
        print(f"  Расхождений: {total_mismatches}")


if __name__ == "__main__":
    asyncio.run(main())

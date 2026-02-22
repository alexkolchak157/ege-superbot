"""
core/benchmark.py
Система бенчмарков для тестирования AI-оценщиков с эталонными ответами.

Позволяет:
- Загружать тестовые кейсы из JSON
- Прогонять через оценщики
- Сравнивать ожидаемые и фактические баллы
- Экспортировать расхождения в JSONL для дообучения
"""

import json
import logging
import os
import asyncio
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

BENCHMARKS_DIR = Path(__file__).parent.parent / "benchmarks"


@dataclass
class CaseResult:
    """Результат прогона одного тестового кейса."""
    case_id: str
    task_type: str
    topic_title: str
    expected_scores: Dict[str, int]
    actual_scores: Dict[str, int]
    expected_total: int
    actual_total: int
    match: bool
    score_diff: int  # actual_total - expected_total
    criteria_diffs: Dict[str, int]  # per-criterion diff
    ai_feedback: str = ""
    notes: str = ""


@dataclass
class BenchmarkReport:
    """Сводный отчёт по бенчмарку."""
    task_type: str
    timestamp: str
    total_cases: int
    exact_matches: int
    total_diff: int  # сумма |diff| по всем кейсам
    avg_diff: float
    cases: List[CaseResult] = field(default_factory=list)
    mismatches: List[CaseResult] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if self.total_cases == 0:
            return 0.0
        return self.exact_matches / self.total_cases * 100

    def summary(self) -> str:
        lines = [
            f"=== Benchmark: {self.task_type} ({self.timestamp}) ===",
            f"Всего кейсов: {self.total_cases}",
            f"Точных совпадений: {self.exact_matches}/{self.total_cases} ({self.accuracy:.0f}%)",
            f"Средняя ошибка: {self.avg_diff:.2f} балла",
            "",
        ]
        if self.mismatches:
            lines.append(f"Расхождения ({len(self.mismatches)}):")
            for m in self.mismatches:
                diffs = ", ".join(
                    f"{k}: {m.expected_scores.get(k, '?')}→{m.actual_scores.get(k, '?')}"
                    for k, d in m.criteria_diffs.items() if d != 0
                )
                lines.append(
                    f"  [{m.case_id}] {m.topic_title}: "
                    f"ожидание={m.expected_total}, факт={m.actual_total} "
                    f"({diffs})"
                )
        else:
            lines.append("Расхождений нет!")

        return "\n".join(lines)


def load_benchmark_cases(task_type: str) -> List[Dict[str, Any]]:
    """Загружает тестовые кейсы для указанного типа задания."""
    benchmark_dir = BENCHMARKS_DIR / task_type
    if not benchmark_dir.exists():
        logger.warning(f"Benchmark directory not found: {benchmark_dir}")
        return []

    cases = []
    for json_file in sorted(benchmark_dir.glob("*.json")):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            file_cases = data.get("cases", [])
            for case in file_cases:
                case["_source_file"] = str(json_file.name)
            cases.extend(file_cases)
            logger.info(f"Loaded {len(file_cases)} cases from {json_file.name}")
        except Exception as e:
            logger.error(f"Error loading {json_file}: {e}")

    return cases


async def _evaluate_task19(case: Dict[str, Any]) -> Tuple[Dict[str, int], int, str]:
    """Прогоняет кейс через оценщик задания 19."""
    from task19.evaluator import Task19AIEvaluator
    evaluator = Task19AIEvaluator()
    result = await evaluator.evaluate(
        answer=case["student_answer"],
        topic=case["topic_title"],
        task_text=case.get("task_text", ""),
        mode="full",
    )
    scores = {}
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        scores = result.criteria_scores
    elif hasattr(result, 'score'):
        scores = {"К1": result.score}
    else:
        scores = {"К1": result.total_score}
    return scores, result.total_score, result.feedback


async def _evaluate_task20(case: Dict[str, Any]) -> Tuple[Dict[str, int], int, str]:
    """Прогоняет кейс через оценщик задания 20."""
    from task20.evaluator import Task20AIEvaluator
    evaluator = Task20AIEvaluator()
    result = await evaluator.evaluate(
        answer=case["student_answer"],
        topic=case["topic_title"],
        task_text=case.get("task_text", ""),
    )
    scores = {}
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        scores = result.criteria_scores
    elif hasattr(result, 'score'):
        scores = {"К1": result.score}
    else:
        scores = {"К1": result.total_score}
    return scores, result.total_score, result.feedback


async def _evaluate_task24(case: Dict[str, Any]) -> Tuple[Dict[str, int], int, str]:
    """Прогоняет кейс через оценщик задания 24."""
    import re
    from task24.checker import evaluate_plan, PlanBotData

    # Загружаем данные планов
    plans_path = Path(__file__).parent.parent / "data" / "plans_data_with_blocks.json"
    with open(plans_path, 'r', encoding='utf-8') as f:
        plans_raw = json.load(f)

    bot_data = PlanBotData(plans_raw)
    topic_name = case["topic_title"]

    # Получаем эталонные данные плана
    ideal_plan_data = bot_data.plans_data.get(topic_name, {})

    feedback = evaluate_plan(
        case["student_answer"],
        ideal_plan_data,
        bot_data,
        topic_name,
    )

    # Извлекаем баллы из текста фидбека
    k1 = 0
    k2 = 0
    m = re.search(r'К1[=:]\s*(\d)', feedback)
    if m:
        k1 = int(m.group(1))
    m = re.search(r'К2[=:]\s*(\d)', feedback)
    if m:
        k2 = int(m.group(1))

    scores = {"К1": k1, "К2": k2}
    total = k1 + k2
    return scores, total, feedback


async def _evaluate_task25(case: Dict[str, Any]) -> Tuple[Dict[str, int], int, str]:
    """Прогоняет кейс через оценщик задания 25."""
    from task25.evaluator import Task25AIEvaluator
    evaluator = Task25AIEvaluator()

    # Для task25 нужен topic как dict с parts
    topic = case.get("topic_data", {})
    if not topic:
        topic = {
            "title": case.get("topic_title", ""),
            "parts": case.get("parts", {}),
            "task_text": case.get("task_text", ""),
        }

    result = await evaluator.evaluate(
        answer=case["student_answer"],
        topic=topic,
    )

    scores = {}
    if hasattr(result, 'criteria_scores') and result.criteria_scores:
        scores = result.criteria_scores
    total = result.total_score
    return scores, total, result.feedback


# Реестр оценщиков
EVALUATORS = {
    "task19": _evaluate_task19,
    "task20": _evaluate_task20,
    "task24": _evaluate_task24,
    "task25": _evaluate_task25,
}


async def run_benchmark(
    task_type: str,
    cases: Optional[List[Dict[str, Any]]] = None,
    case_ids: Optional[List[str]] = None,
) -> BenchmarkReport:
    """
    Запускает бенчмарк для указанного типа задания.

    Args:
        task_type: Тип задания (task19, task20, task24, task25)
        cases: Список кейсов (если None, загружаются из файлов)
        case_ids: Фильтр по ID кейсов (если None, прогоняются все)

    Returns:
        BenchmarkReport с результатами
    """
    if task_type not in EVALUATORS:
        raise ValueError(f"Unknown task type: {task_type}. Available: {list(EVALUATORS.keys())}")

    if cases is None:
        cases = load_benchmark_cases(task_type)

    if not cases:
        return BenchmarkReport(
            task_type=task_type,
            timestamp=datetime.now().isoformat(),
            total_cases=0,
            exact_matches=0,
            total_diff=0,
            avg_diff=0.0,
        )

    if case_ids:
        cases = [c for c in cases if c.get("id") in case_ids]

    evaluate_fn = EVALUATORS[task_type]
    report = BenchmarkReport(
        task_type=task_type,
        timestamp=datetime.now().isoformat(),
        total_cases=len(cases),
        exact_matches=0,
        total_diff=0,
        avg_diff=0.0,
    )

    for i, case in enumerate(cases, 1):
        case_id = case.get("id", f"case_{i}")
        logger.info(f"[{i}/{len(cases)}] Running {case_id}...")

        try:
            actual_scores, actual_total, feedback = await evaluate_fn(case)
        except Exception as e:
            logger.error(f"Error evaluating {case_id}: {e}", exc_info=True)
            actual_scores = {}
            actual_total = -1
            feedback = f"ERROR: {e}"

        expected_scores = case.get("expected_scores", {})
        expected_total = case.get("expected_total", sum(expected_scores.values()))

        # Нормализуем ключи (К1/k1 → К1)
        norm_actual = _normalize_score_keys(actual_scores)
        norm_expected = _normalize_score_keys(expected_scores)

        criteria_diffs = {}
        all_keys = set(list(norm_expected.keys()) + list(norm_actual.keys()))
        for k in all_keys:
            criteria_diffs[k] = norm_actual.get(k, 0) - norm_expected.get(k, 0)

        diff = actual_total - expected_total
        is_match = actual_total == expected_total and all(
            d == 0 for d in criteria_diffs.values()
        )

        case_result = CaseResult(
            case_id=case_id,
            task_type=task_type,
            topic_title=case.get("topic_title", ""),
            expected_scores=norm_expected,
            actual_scores=norm_actual,
            expected_total=expected_total,
            actual_total=actual_total,
            match=is_match,
            score_diff=diff,
            criteria_diffs=criteria_diffs,
            ai_feedback=feedback[:500] if feedback else "",
            notes=case.get("notes", ""),
        )

        report.cases.append(case_result)
        if is_match:
            report.exact_matches += 1
        else:
            report.mismatches.append(case_result)

        report.total_diff += abs(diff)

    report.avg_diff = report.total_diff / report.total_cases if report.total_cases else 0.0
    return report


def _normalize_score_keys(scores: Dict[str, int]) -> Dict[str, int]:
    """Нормализует ключи баллов: k1→К1, К1→К1."""
    normalized = {}
    for key, val in scores.items():
        norm_key = key.upper().replace("K", "К")  # latin K → cyrillic К
        if not norm_key.startswith("К"):
            norm_key = f"К{norm_key}"
        # Убираем _score суффикс
        norm_key = norm_key.replace("_SCORE", "")
        normalized[norm_key] = int(val) if val is not None else 0
    return normalized


def export_mismatches_jsonl(report: BenchmarkReport, output_path: Optional[str] = None) -> str:
    """
    Экспортирует расхождения в JSONL для дообучения.

    Каждая строка содержит:
    - prompt: задание + ответ ученика
    - expected_completion: правильная оценка
    - actual_completion: неправильная оценка AI
    - metadata: контекст для анализа

    Returns:
        Путь к файлу
    """
    if output_path is None:
        results_dir = BENCHMARKS_DIR / "results"
        results_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(
            results_dir / f"mismatches_{report.task_type}_{timestamp}.jsonl"
        )

    with open(output_path, 'w', encoding='utf-8') as f:
        for case_result in report.mismatches:
            record = {
                "case_id": case_result.case_id,
                "task_type": case_result.task_type,
                "topic": case_result.topic_title,
                "expected_scores": case_result.expected_scores,
                "expected_total": case_result.expected_total,
                "actual_scores": case_result.actual_scores,
                "actual_total": case_result.actual_total,
                "criteria_diffs": case_result.criteria_diffs,
                "ai_feedback": case_result.ai_feedback,
                "notes": case_result.notes,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"Exported {len(report.mismatches)} mismatches to {output_path}")
    return output_path


def save_report_json(report: BenchmarkReport, output_path: Optional[str] = None) -> str:
    """Сохраняет полный отчёт в JSON."""
    if output_path is None:
        results_dir = BENCHMARKS_DIR / "results"
        results_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(
            results_dir / f"report_{report.task_type}_{timestamp}.json"
        )

    data = {
        "task_type": report.task_type,
        "timestamp": report.timestamp,
        "total_cases": report.total_cases,
        "exact_matches": report.exact_matches,
        "accuracy": report.accuracy,
        "avg_diff": report.avg_diff,
        "cases": [asdict(c) for c in report.cases],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"Report saved to {output_path}")
    return output_path

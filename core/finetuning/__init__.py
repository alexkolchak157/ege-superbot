"""
Модуль дообучения (fine-tuning) YandexGPT на экспертных оценках.

Включает:
- data_exporter: Экспорт данных из БД в формат JSONL для дообучения
- tuning_service: Управление задачами дообучения через API YandexGPT
"""

from core.finetuning.data_exporter import TrainingDataExporter
from core.finetuning.tuning_service import YandexGPTTuningService

__all__ = ["TrainingDataExporter", "YandexGPTTuningService"]

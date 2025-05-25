import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple

try:
    from .config import QUESTIONS_FILE
except ImportError:
    QUESTIONS_FILE = "questions.json"

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Глобальные переменные ---
QUESTIONS_DATA: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = None
QUESTIONS_LIST_FLAT: Optional[List[Dict[str, Any]]] = None
QUESTIONS_DICT_FLAT: Optional[Dict[str, Dict[str, Any]]] = None
AVAILABLE_BLOCKS: Optional[List[str]] = None

# --- Загрузка и обработка вопросов ---
def load_questions() -> Tuple[Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]], Optional[List[Dict[str, Any]]]]:
    global QUESTIONS_DATA, QUESTIONS_LIST_FLAT, QUESTIONS_DICT_FLAT, AVAILABLE_BLOCKS
    if not os.path.exists(QUESTIONS_FILE):
        logging.error(f"Файл с вопросами '{QUESTIONS_FILE}' не найден.")
        return None, None

    try:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            QUESTIONS_LIST_RAW = json.load(f)
    except json.JSONDecodeError as e:
        logging.critical(f"Ошибка декодирования JSON в файле '{QUESTIONS_FILE}': {e}")
        return None, None
    except Exception as e:
        logging.critical(f"Не удалось прочитать файл '{QUESTIONS_FILE}': {e}")
        return None, None

    processed_questions: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    processed_list_flat: List[Dict[str, Any]] = []
    question_count = 0

    if not isinstance(QUESTIONS_LIST_RAW, list):
        logging.critical(f"Ошибка структуры JSON: Ожидался список вопросов, получен {type(QUESTIONS_LIST_RAW)}")
        return None, None

    for question in QUESTIONS_LIST_RAW:
        if not isinstance(question, dict):
            logging.warning(f"Элемент в списке вопросов не является словарем: {str(question)[:100]}... Пропуск.")
            continue
        base_keys = ["block", "topic", "id", "answer", "type"]
        if not all(k in question for k in base_keys):
            logging.warning(f"Вопрос пропущен (нет базовых полей block/topic/id/answer/type): {str(question)[:100]}...")
            continue
        question_type = question.get("type")
        if question_type == "matching":
            matching_keys = ["instruction", "column1_options", "column2_options"]
            if not all(k in question for k in matching_keys):
                logging.warning(f"Вопрос matching пропущен (нет instruction/column1_options/column2_options): ID={question.get('id')}")
                continue
            if not isinstance(question.get("column1_options"), dict) or not isinstance(question.get("column2_options"), dict):
                logging.warning(f"Вопрос matching пропущен (опции не являются словарями): ID={question.get('id')}")
                continue
        elif question_type in ["single_choice", "multiple_choice", "sequence", "text_input"]:
            if "question" not in question:
                logging.warning(f"Вопрос {question_type} пропущен (нет поля 'question'): ID={question.get('id')}")
                continue
        else:
            logging.warning(f"Неизвестный тип вопроса '{question_type}' для ID={question.get('id')}. Пропуск.")
            continue

        block = question["block"]
        topic = question["topic"]

        if block not in processed_questions:
            processed_questions[block] = {}
        if topic not in processed_questions[block]:
            processed_questions[block][topic] = []

        processed_questions[block][topic].append(question)
        processed_list_flat.append(question)
        question_count += 1

    logging.info(f"Загружено и обработано вопросов: {question_count}")

    # --- Глобальные переменные ---
    QUESTIONS_DATA = processed_questions
    QUESTIONS_LIST_FLAT = processed_list_flat
    QUESTIONS_DICT_FLAT = {q["id"]: q for q in processed_list_flat if isinstance(q, dict) and "id" in q}
    AVAILABLE_BLOCKS = sorted(list(QUESTIONS_DATA.keys())) if QUESTIONS_DATA else []

    return QUESTIONS_DATA, QUESTIONS_LIST_FLAT

def get_questions_data() -> Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]]:
    global QUESTIONS_DATA
    if QUESTIONS_DATA is None:
        logging.warning("Попытка доступа к QUESTIONS_DATA до загрузки.")
    return QUESTIONS_DATA

def get_questions_list_flat() -> Optional[List[Dict[str, Any]]]:
    global QUESTIONS_LIST_FLAT
    if QUESTIONS_LIST_FLAT is None:
        logging.warning("Попытка доступа к QUESTIONS_LIST_FLAT до загрузки.")
    return QUESTIONS_LIST_FLAT

def get_questions_dict_flat() -> Optional[Dict[str, Dict[str, Any]]]:
    global QUESTIONS_DICT_FLAT
    if QUESTIONS_DICT_FLAT is None:
        logging.warning("Попытка доступа к QUESTIONS_DICT_FLAT до загрузки.")
    return QUESTIONS_DICT_FLAT

# --- Загрузи вопросы при импорте (или вызови вручную в app.py при старте) ---
load_questions()

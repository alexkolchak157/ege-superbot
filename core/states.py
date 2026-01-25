"""Состояния FSM для PTB ConversationHandler."""

# Общие состояния
CHOOSING_SECTION = 1      # Выбор test_part или task24
CHOOSING_MODE = 2         # Выбор режима работы
CHOOSING_BLOCK = 3        # Выбор блока
CHOOSING_TOPIC = 4        # Выбор темы
CHOOSING_EXAM_NUMBER = 5  # Выбор номера ЕГЭ
ANSWERING = 6            # Ответ на вопрос
CHOOSING_NEXT_ACTION = 7  # После ответа
REVIEWING_MISTAKES = 8    # Работа над ошибками
EXAM_MODE = 9  # Режим экзамена

# Состояния для task19
SELECTING_TOPIC = 10     # Выбор темы для task19
WAITING_ANSWER = 11      # Ожидание ответа для task19
SEARCHING = 12

# Состояния для task24
AWAITING_PLAN = 20       # Ожидание плана от пользователя
SHOWING_PLAN = 21        # Показ эталонного плана
AWAITING_SEARCH = 22     # Ожидание поискового запроса
AWAITING_FEEDBACK = 23     

# Новые состояния для task25
CHOOSING_BLOCK_T25 = 101  # Выбор блока тем
ANSWERING_PARTS = 102  # Ответ по частям
# Уникальные состояния для изоляции модулей
TASK19_WAITING = 119  # Состояние ожидания ответа task19
TASK20_WAITING = 120  # Состояние ожидания ответа task20
TASK25_WAITING = 125  # Состояние ожидания ответа task25
# Состояния для task20
ANSWERING_T20 = 2001
SEARCHING = 2002
VIEWING_EXAMPLE = 2003
CONFIRMING_RESET = 2004

# Состояния для task21
ANSWERING_T21 = 2101

# Состояния для task22
ANSWERING_T22 = 2201

# Состояния для task23
ANSWERING_T23 = 2301
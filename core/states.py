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

# Состояния для task19
SELECTING_TOPIC = 10     # Выбор темы для task19
WAITING_ANSWER = 11      # Ожидание ответа для task19
SEARCHING = 'searching'

# Состояния для task24
AWAITING_PLAN = 20       # Ожидание плана от пользователя
SHOWING_PLAN = 21        # Показ эталонного плана
AWAITING_SEARCH = 22     # Ожидание поискового запроса
AWAITING_FEEDBACK = 23     

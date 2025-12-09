"""
FSM состояния для режима учителя.
"""

from enum import IntEnum


class TeacherStates(IntEnum):
    """Состояния для учителей"""
    # Регистрация
    TEACHER_MENU = 1
    AWAITING_TEACHER_NAME = 2

    # Управление учениками
    STUDENT_LIST = 10
    STUDENT_DETAIL = 11

    # Создание домашнего задания
    CREATE_ASSIGNMENT = 20
    SELECT_ASSIGNMENT_TYPE = 21
    SELECT_SELECTION_MODE = 22  # Способ отбора заданий (все/темы/номера)
    SELECT_TOPICS = 23  # Выбор тем/блоков из банка
    SELECT_SPECIFIC_QUESTIONS = 24  # Выбор конкретных заданий из выбранных блоков
    ENTER_QUESTION_NUMBERS = 25  # Ввод конкретных номеров заданий
    ENTER_QUESTION_COUNT = 26  # Ввод количества случайных заданий для режима "все"
    ENTER_ASSIGNMENT_TITLE = 27  # Ввод названия домашнего задания

    # Просмотр статистики
    VIEW_STATISTICS = 30

    # Дарение подписок
    GIFT_SUBSCRIPTION_MENU = 40
    SELECT_STUDENT_FOR_GIFT = 41
    SELECT_GIFT_DURATION = 42
    CONFIRM_GIFT = 43

    # Промокоды
    CREATE_PROMO_CODE = 50
    SET_PROMO_USES = 51
    SET_PROMO_DURATION = 52

    # Проверка ответов учеников
    ENTERING_COMMENT = 60  # Ввод комментария к ответу ученика
    OVERRIDING_SCORE = 61  # Переоценка ответа

    # Кастомные задания
    ENTER_CUSTOM_QUESTION = 70  # Ввод текста кастомного вопроса
    REVIEW_CUSTOM_QUESTIONS = 71  # Просмотр и подтверждение всех вопросов
    SELECT_CUSTOM_QUESTION_TYPE = 72  # Выбор типа задания для кастомного вопроса
    ENTER_CUSTOM_QUESTION_ANSWER = 73  # Ввод правильного ответа/критериев оценки

    # Браузер заданий
    BROWSER_SEARCH = 74  # Поиск заданий в браузере

    # Оплата подписки
    PAYMENT_ENTERING_PROMO = 80  # Ввод промокода для оплаты подписки
    PAYMENT_ENTERING_EMAIL = 81  # Ввод email для оплаты подписки
    PAYMENT_AUTO_RENEWAL_CHOICE = 82  # Выбор типа оплаты (с автопродлением или разовая)


class StudentStates(IntEnum):
    """Состояния для учеников (связь с учителем)"""
    # Подключение к учителю
    ENTER_TEACHER_CODE = 100
    CONFIRM_TEACHER = 101

    # Домашние задания
    HOMEWORK_LIST = 110
    HOMEWORK_DETAIL = 111
    DOING_HOMEWORK = 112

    # Активация промокода
    ENTER_PROMO_CODE = 120

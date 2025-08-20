#!/bin/bash

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}    🔄 Безопасное обновление EGE-бота${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"

# 1. Создаем бэкап
echo -e "\n${YELLOW}📦 Создание резервной копии перед обновлением...${NC}"
/opt/ege-bot/scripts/backup.sh manual

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Ошибка создания бэкапа! Обновление отменено.${NC}"
    exit 1
fi

# 2. Останавливаем бота
echo -e "\n${YELLOW}⏹️  Остановка бота...${NC}"
bot_pid=$(pgrep -f "python.*core/app.py")

if [ -n "$bot_pid" ]; then
    kill -TERM $bot_pid
    sleep 5
    
    if kill -0 $bot_pid 2>/dev/null; then
        echo -e "${YELLOW}Принудительная остановка...${NC}"
        kill -9 $bot_pid
    fi
    echo -e "${GREEN}✓ Бот остановлен${NC}"
else
    echo "Процесс бота не найден"
fi

# 3. Сохраняем текущую версию
echo -e "\n${YELLOW}📝 Сохранение информации о текущей версии...${NC}"
cd /opt/ege-bot
if [ -d .git ]; then
    CURRENT_COMMIT=$(git rev-parse HEAD)
    echo "Текущий коммит: $CURRENT_COMMIT"
    echo $CURRENT_COMMIT > /opt/ege-bot/backups/last_version.txt
fi

# 4. Обновляем код
echo -e "\n${YELLOW}📥 Получение обновлений из репозитория...${NC}"
git pull

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Ошибка при обновлении кода!${NC}"
    echo -e "${YELLOW}Попытка сброса изменений и повторного обновления...${NC}"
    
    # Сохраняем локальные изменения
    git stash
    
    # Пробуем обновить снова
    git pull
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ Не удалось обновить код. Требуется ручное вмешательство.${NC}"
        exit 1
    fi
fi

NEW_COMMIT=$(git rev-parse HEAD)
echo -e "${GREEN}✓ Код обновлен до версии: $NEW_COMMIT${NC}"

# 5. Обновляем зависимости (если есть requirements.txt)
if [ -f "requirements.txt" ]; then
    echo -e "\n${YELLOW}📦 Обновление зависимостей Python...${NC}"
    pip3 install -r requirements.txt --upgrade
fi

# 6. Проверяем целостность файлов
echo -e "\n${YELLOW}🔍 Проверка важных файлов...${NC}"
[ -f "/opt/ege-bot/core/app.py" ] && echo -e "${GREEN}  ✓ core/app.py${NC}" || echo -e "${RED}  ✗ core/app.py${NC}"
[ -f "/opt/ege-bot/bot_persistence.pickle" ] && echo -e "${GREEN}  ✓ bot_persistence.pickle${NC}" || echo -e "${YELLOW}  ⚠ bot_persistence.pickle (будет создан при запуске)${NC}"
[ -f "/opt/ege-bot/.env" ] && echo -e "${GREEN}  ✓ .env${NC}" || echo -e "${RED}  ✗ .env${NC}"

# 7. Запускаем бота
echo -e "\n${YELLOW}▶️  Запуск обновленного бота...${NC}"
cd /opt/ege-bot
nohup python3 core/app.py > logs/bot.log 2>&1 &
NEW_PID=$!

sleep 3

# 8. Проверяем, что бот запустился
if kill -0 $NEW_PID 2>/dev/null; then
    echo -e "${GREEN}✅ Бот успешно запущен! PID: $NEW_PID${NC}"
    echo -e "\nДля просмотра логов используйте:"
    echo -e "  ${BLUE}tail -f /opt/ege-bot/logs/bot.log${NC}"
else
    echo -e "${RED}❌ Бот не запустился! Проверьте логи.${NC}"
    echo -e "\n${YELLOW}Последние строки из лога:${NC}"
    tail -n 20 /opt/ege-bot/logs/bot.log
    
    echo -e "\n${YELLOW}Для восстановления предыдущей версии используйте:${NC}"
    echo -e "  ${BLUE}/opt/ege-bot/scripts/restore.sh${NC}"
    exit 1
fi

echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Обновление завершено успешно!${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"
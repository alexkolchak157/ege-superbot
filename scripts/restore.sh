#!/bin/bash

# =====================================================
# Скрипт восстановления EGE-бота
# =====================================================

BOT_DIR="/opt/ege-bot"
BACKUP_DIR="$BOT_DIR/backups"

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}    📥 Восстановление EGE-бота${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}"

# Остановка бота
stop_bot() {
    echo -e "\n${YELLOW}⏹️  Останавливаем бота...${NC}"
    
    # Ищем процесс
    bot_pid=$(pgrep -f "python.*core/app.py")
    
    if [ -n "$bot_pid" ]; then
        echo "Найден процесс: PID $bot_pid"
        kill -TERM $bot_pid
        sleep 5
        
        # Проверяем, остановился ли
        if ! kill -0 $bot_pid 2>/dev/null; then
            echo -e "${GREEN}✓ Бот остановлен${NC}"
        else
            echo -e "${YELLOW}Принудительная остановка...${NC}"
            kill -9 $bot_pid
        fi
    else
        echo "Процесс бота не найден"
    fi
}

# Показать доступные бэкапы
show_backups() {
    echo -e "\n${YELLOW}📦 Последние доступные бэкапы:${NC}\n"
    
    # Собираем все бэкапы
    all_backups=()
    for type in hourly daily manual; do
        if [ -d "$BACKUP_DIR/$type" ]; then
            while IFS= read -r backup; do
                if [ -n "$backup" ]; then
                    all_backups+=("$backup")
                fi
            done < <(find "$BACKUP_DIR/$type" -name "*.tar.gz" -type f 2>/dev/null)
        fi
    done
    
    # Сортируем по дате
    IFS=$'\n' sorted_backups=($(printf '%s\n' "${all_backups[@]}" | xargs ls -t 2>/dev/null))
    
    if [ ${#sorted_backups[@]} -eq 0 ]; then
        echo -e "${RED}Нет доступных бэкапов!${NC}"
        exit 1
    fi
    
    # Показываем список (максимум 15 последних)
    for i in "${!sorted_backups[@]}"; do
        if [ $i -ge 15 ]; then break; fi
        backup="${sorted_backups[$i]}"
        size=$(du -h "$backup" | cut -f1)
        date=$(stat -c %y "$backup" | cut -d' ' -f1,2 | cut -d'.' -f1)
        type=$(echo "$backup" | awk -F'/' '{print $(NF-1)}')
        echo "$((i+1))) [${type}] $(basename "$backup") ($size, $date)"
    done
    
    echo -e "\n${YELLOW}Выберите номер бэкапа для восстановления:${NC}"
    read -p "> " choice
    
    if [ "$choice" -ge 1 ] && [ "$choice" -le "${#sorted_backups[@]}" ]; then
        selected_backup="${sorted_backups[$((choice-1))]}"
        echo -e "\n${GREEN}Выбран: $(basename "$selected_backup")${NC}"
        return 0
    else
        echo -e "${RED}Неверный выбор!${NC}"
        exit 1
    fi
}

# Восстановление
restore() {
    echo -e "\n${YELLOW}📥 Восстановление из бэкапа...${NC}"
    
    # Создаем резервную копию текущих файлов
    timestamp=$(date +%Y%m%d_%H%M%S)
    echo -e "${YELLOW}Создаем бэкап текущих файлов...${NC}"
    
    cd "$BOT_DIR"
    current_backup="$BACKUP_DIR/manual/before_restore_$timestamp.tar.gz"
    tar -czf "$current_backup" bot_persistence.pickle quiz_async.db .env data 2>/dev/null
    echo -e "${GREEN}✓ Текущие файлы сохранены в: $(basename "$current_backup")${NC}"
    
    # Распаковываем выбранный бэкап
    echo -e "\n${YELLOW}Распаковка бэкапа...${NC}"
    tar -xzf "$selected_backup" -C "$BOT_DIR"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Восстановление завершено успешно!${NC}"
        
        # Показываем восстановленные файлы
        echo -e "\n${BLUE}Восстановленные файлы:${NC}"
        [ -f "$BOT_DIR/bot_persistence.pickle" ] && echo "  ✓ bot_persistence.pickle"
        [ -f "$BOT_DIR/quiz_async.db" ] && echo "  ✓ quiz_async.db"
        [ -f "$BOT_DIR/.env" ] && echo "  ✓ .env"
        [ -d "$BOT_DIR/data" ] && echo "  ✓ data/"
    else
        echo -e "${RED}❌ Ошибка при восстановлении!${NC}"
        exit 1
    fi
}

# Главная логика
echo -e "\n${RED}⚠️  ВНИМАНИЕ: Бот будет остановлен для восстановления!${NC}"
echo -e "Текущие файлы будут сохранены в резервную копию."
read -p "Продолжить? (y/n): " confirm

if [ "$confirm" != "y" ]; then
    echo "Отменено"
    exit 0
fi

# Выбираем бэкап
show_backups

# Останавливаем бота
stop_bot

# Восстанавливаем
restore

# Предлагаем запустить бота
echo -e "\n${YELLOW}Запустить бота? (y/n):${NC}"
read -p "> " start_bot

if [ "$start_bot" = "y" ]; then
    echo -e "${GREEN}Запускаем бота...${NC}"
    cd "$BOT_DIR"
    nohup python3 core/app.py > logs/bot.log 2>&1 &
    echo -e "${GREEN}✓ Бот запущен (PID: $!)${NC}"
    echo -e "Логи: tail -f $BOT_DIR/logs/bot.log"
fi

echo -e "\n${GREEN}✅ Готово!${NC}"
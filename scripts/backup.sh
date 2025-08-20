#!/bin/bash

# =====================================================
# Скрипт резервного копирования EGE-бота
# =====================================================

# Конфигурация
BOT_DIR="/opt/ege-bot"
BACKUP_DIR="$BOT_DIR/backups"
PERSISTENCE_FILE="$BOT_DIR/bot_persistence.pickle"
DB_FILE="$BOT_DIR/quiz_async.db"
LOG_FILE="$BOT_DIR/logs/backup.log"

# Telegram уведомления (ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ!)

BOT_TOKEN="8143999018:AAF13bXZgCMJW4oQudTxR6YzJQ7Cc0UKDa0"
ADMIN_CHAT_ID="149841646"

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Функция логирования
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
    echo -e "$1"
}

# Функция отправки уведомления в Telegram
send_telegram_notification() {
    if [ -n "$BOT_TOKEN" ] && [ -n "$ADMIN_CHAT_ID" ]; then
        local message="$1"
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d "chat_id=${ADMIN_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1
    fi
}

# Основная функция создания бэкапа
create_backup() {
    local backup_type=${1:-manual}
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_name="backup_${timestamp}.tar.gz"
    local backup_path="$BACKUP_DIR/$backup_type"
    
    # Создаем директорию если нет
    mkdir -p "$backup_path"
    
    log_message "${YELLOW}📦 Создание $backup_type бэкапа...${NC}"
    
    # Переходим в директорию бота
    cd "$BOT_DIR"
    
    # Список файлов для бэкапа
    FILES_TO_BACKUP=""
    
    # Проверяем наличие файлов
    if [ -f "$PERSISTENCE_FILE" ]; then
        FILES_TO_BACKUP="$FILES_TO_BACKUP bot_persistence.pickle"
        log_message "${GREEN}✓ Найден файл персистентности${NC}"
    else
        log_message "${RED}✗ Файл персистентности не найден${NC}"
    fi
    
    if [ -f "$DB_FILE" ]; then
        FILES_TO_BACKUP="$FILES_TO_BACKUP quiz_async.db"
        log_message "${GREEN}✓ Найдена база данных${NC}"
    else
        log_message "${YELLOW}⚠ База данных не найдена${NC}"
    fi
    
    if [ -f "$BOT_DIR/.env" ]; then
        FILES_TO_BACKUP="$FILES_TO_BACKUP .env"
        log_message "${GREEN}✓ Найден файл конфигурации${NC}"
    fi
    
    # Добавляем папку data если она существует
    if [ -d "$BOT_DIR/data" ]; then
        FILES_TO_BACKUP="$FILES_TO_BACKUP data"
        log_message "${GREEN}✓ Найдена папка data${NC}"
    fi
    
    # Создаем архив
    if [ -n "$FILES_TO_BACKUP" ]; then
        tar -czf "$backup_path/$backup_name" $FILES_TO_BACKUP 2>/dev/null
        
        # Проверяем размер созданного бэкапа
        backup_size=$(du -h "$backup_path/$backup_name" | cut -f1)
        
        log_message "${GREEN}✅ Бэкап создан: $backup_name (размер: $backup_size)${NC}"
        
        # Отправляем уведомление
        send_telegram_notification "✅ <b>Резервная копия создана</b>
Тип: $backup_type
Файл: $backup_name
Размер: $backup_size"
        
        # Возвращаем путь к бэкапу
        echo "$backup_path/$backup_name"
    else
        log_message "${RED}❌ Нет файлов для бэкапа!${NC}"
        send_telegram_notification "❌ Ошибка создания бэкапа: файлы не найдены"
        return 1
    fi
}

# Функция очистки старых бэкапов
cleanup_old_backups() {
    local backup_type=$1
    local keep_count=$2
    
    log_message "${YELLOW}🧹 Очистка старых $backup_type бэкапов...${NC}"
    
    cd "$BACKUP_DIR/$backup_type"
    
    # Подсчитываем количество бэкапов
    backup_count=$(ls -1 *.tar.gz 2>/dev/null | wc -l)
    
    if [ $backup_count -gt $keep_count ]; then
        # Удаляем старые, оставляя последние N
        ls -1t *.tar.gz | tail -n +$((keep_count + 1)) | while read file; do
            log_message "  Удаление: $file"
            rm "$file"
        done
        
        deleted_count=$((backup_count - keep_count))
        log_message "${GREEN}✓ Удалено старых бэкапов: $deleted_count${NC}"
    else
        log_message "  Очистка не требуется (всего бэкапов: $backup_count)"
    fi
}

# Функция проверки места на диске
check_disk_space() {
    local usage=$(df /opt | awk 'NR==2 {print int($5)}')
    local available=$(df -h /opt | awk 'NR==2 {print $4}')
    
    log_message "💾 Использование диска: ${usage}%, доступно: ${available}"
    
    if [ $usage -gt 85 ]; then
        log_message "${RED}⚠️  ВНИМАНИЕ: Мало места на диске!${NC}"
        send_telegram_notification "⚠️ <b>Внимание!</b>
Использование диска: ${usage}%
Доступно: ${available}
Рекомендуется очистить старые бэкапы!"
    fi
}

# === ГЛАВНАЯ ЛОГИКА ===
main() {
    log_message "════════════════════════════════════════"
    log_message "🚀 Запуск резервного копирования EGE-бота"
    
    # Определяем тип бэкапа
    backup_type=${1:-manual}
    
    # Проверяем место на диске
    check_disk_space
    
    # Создаем бэкап
    backup_file=$(create_backup "$backup_type")
    
    if [ $? -eq 0 ]; then
        # Очищаем старые бэкапы
        case $backup_type in
            hourly)
                cleanup_old_backups "hourly" 24  # Храним последние 24 часа
                ;;
            daily)
                cleanup_old_backups "daily" 30   # Храним последние 30 дней
                ;;
            manual)
                cleanup_old_backups "manual" 10  # Храним последние 10 ручных
                ;;
        esac
        
        # Показываем статистику
        total_backups=$(find "$BACKUP_DIR" -name "*.tar.gz" | wc -l)
        total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)
        
        log_message "📊 Статистика:"
        log_message "  Всего бэкапов: $total_backups"
        log_message "  Общий размер: $total_size"
        
        log_message "${GREEN}✅ Резервное копирование завершено успешно${NC}"
    else
        log_message "${RED}❌ Резервное копирование завершено с ошибками${NC}"
    fi
    
    log_message "════════════════════════════════════════"
}

# Запускаем скрипт
main "$@"
#!/bin/bash

echo "======================================"
echo "     📊 Статус EGE-бота"
echo "======================================"

# Проверка процесса
if pgrep -f "python.*core/app.py" > /dev/null; then
    PID=$(pgrep -f 'python.*core/app.py')
    UPTIME=$(ps -o etime= -p $PID | xargs)
    echo "✅ Бот: РАБОТАЕТ"
    echo "   PID: $PID"
    echo "   Время работы: $UPTIME"
else
    echo "❌ Бот: НЕ РАБОТАЕТ"
fi

echo "--------------------------------------"

# Проверка файла персистентности
if [ -f "/opt/ege-bot/bot_persistence.pickle" ]; then
    SIZE=$(du -h /opt/ege-bot/bot_persistence.pickle | cut -f1)
    MODIFIED=$(stat -c %y /opt/ege-bot/bot_persistence.pickle | cut -d'.' -f1)
    
    # Проверяем, насколько свежий файл
    CURRENT_TIME=$(date +%s)
    FILE_TIME=$(date -d "$MODIFIED" +%s)
    DIFF=$((CURRENT_TIME - FILE_TIME))
    
    echo "✅ Персистентность: НАЙДЕНА"
    echo "   Размер: $SIZE"
    echo "   Обновлена: $MODIFIED"
    
    if [ $DIFF -gt 3600 ]; then
        echo "   ⚠️  Файл не обновлялся более часа!"
    fi
else
    echo "❌ Персистентность: НЕ НАЙДЕНА"
fi

echo "--------------------------------------"

# Проверка базы данных
if [ -f "/opt/ege-bot/quiz_async.db" ]; then
    SIZE=$(du -h /opt/ege-bot/quiz_async.db | cut -f1)
    echo "✅ База данных: $SIZE"
else
    echo "❌ База данных: НЕ НАЙДЕНА"
fi

echo "--------------------------------------"

# Статистика бэкапов
TOTAL_BACKUPS=$(find /opt/ege-bot/backups -name "*.tar.gz" 2>/dev/null | wc -l)
BACKUP_SIZE=$(du -sh /opt/ege-bot/backups 2>/dev/null | cut -f1)

echo "📦 Резервные копии:"
echo "   Всего: $TOTAL_BACKUPS файлов"
echo "   Размер: $BACKUP_SIZE"

# Последние бэкапы
echo "   Последние:"
for type in manual daily hourly; do
    LATEST=$(ls -t /opt/ege-bot/backups/$type/*.tar.gz 2>/dev/null | head -1)
    if [ -n "$LATEST" ]; then
        WHEN=$(stat -c %y "$LATEST" | cut -d'.' -f1)
        SIZE=$(du -h "$LATEST" | cut -f1)
        echo "   • $type: $(basename $LATEST) ($SIZE)"
    fi
done

echo "--------------------------------------"

# Место на диске
DISK_USAGE=$(df -h /opt | awk 'NR==2 {print $5}' | sed 's/%//')
DISK_FREE=$(df -h /opt | awk 'NR==2 {print $4}')
DISK_TOTAL=$(df -h /opt | awk 'NR==2 {print $2}')

echo "💾 Диск (/opt):"
echo "   Использовано: ${DISK_USAGE}%"
echo "   Свободно: $DISK_FREE из $DISK_TOTAL"

if [ $DISK_USAGE -gt 85 ]; then
    echo "   ⚠️  ВНИМАНИЕ: Мало свободного места!"
fi

echo "--------------------------------------"

# Проверка логов
if [ -d "/opt/ege-bot/logs" ]; then
    LOG_COUNT=$(ls -1 /opt/ege-bot/logs/*.log 2>/dev/null | wc -l)
    LOG_SIZE=$(du -sh /opt/ege-bot/logs 2>/dev/null | cut -f1)
    echo "📝 Логи:"
    echo "   Файлов: $LOG_COUNT"
    echo "   Размер: $LOG_SIZE"
    
    # Последние ошибки
    if [ -f "/opt/ege-bot/logs/bot.log" ]; then
        ERRORS=$(tail -n 100 /opt/ege-bot/logs/bot.log | grep -c "ERROR")
        if [ $ERRORS -gt 0 ]; then
            echo "   ⚠️  Ошибок в последних 100 строках: $ERRORS"
        fi
    fi
fi

echo "======================================"
import json

# Читаем старый формат
with open('data/plans_data_with_blocks.json', 'r', encoding='utf-8') as f:
    old_data = json.load(f)

# Создаем новую структуру
new_data = {
    "plans": {},
    "blocks": {
        "Человек и общество": [],
        "Экономика": [],
        "Социальные отношения": [],
        "Политика": [],
        "Право": []
    }
}

# Преобразуем данные
for item in old_data:
    if isinstance(item, dict):
        for topic_name, topic_data in item.items():
            # Добавляем план
            new_data["plans"][topic_name] = topic_data
            
            # Определяем блок и добавляем тему в соответствующий блок
            block = topic_data.get("block", "Без блока")
            if block in new_data["blocks"]:
                new_data["blocks"][block].append(topic_name)
            else:
                # Если блок не предопределен, создаем его
                new_data["blocks"][block] = [topic_name]

# Сохраняем в новом формате
with open('data/plans_data_with_blocks_new.json', 'w', encoding='utf-8') as f:
    json.dump(new_data, f, ensure_ascii=False, indent=2)

print("Преобразование завершено!")
print(f"Всего планов: {len(new_data['plans'])}")
for block, topics in new_data['blocks'].items():
    print(f"Блок '{block}': {len(topics)} тем")
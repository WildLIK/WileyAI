package ru.wildlik.wileyai.mobile;

import java.util.List;

/** Only installed code is marked available. No speculative download metadata. */
final class ComponentCatalog {
    record Entry(String name, String description) {}
    static List<Entry> entries() {
        return java.util.Arrays.asList(
            new Entry("Команды телефона · встроено", "Русские текстовые команды, запуск приложений, музыка и громкость. Без LLM и сети. Дополнительная загрузка: 0 Б. Версия: 0.4.0. Источник: исходники WileyAI / PhoneCommands и PhoneActionEngine. Лицензия отдельного компонента не указана."),
            new Entry("Языковая модель телефона · не подключена", "Движок GGUF ещё не интегрирован. Локального разговорного ИИ в этой версии нет. Загрузка и импорт появятся после проверки движка. Модели не протестированы; размеры, лицензии и совместимость не определены."),
            new Entry("Облака Android · запланировано", "Прямые адаптеры OpenRouter, OpenAI и совместимых API ещё не подключены. Аккаунты и ключи компьютера не копируются. Каталога облачных моделей и диагностики их доступности пока нет.")
        );
    }
}

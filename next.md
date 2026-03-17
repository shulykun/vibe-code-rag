Коротко: что ещё не хватает
Если смотреть на PROJECT_REQUIREMENTS.md + use-cases.md, то:
Нет полноценного DependencyGraph на реальном коде
не извлекаем связи кто кого вызывает, кто использует класс/интерфейс;
analyze_impact, объяснения цепочек вызовов и часть архитектурных запросов пока невозможны.
Нет понимания фреймворков и домена
Spring/JPA/тестовые аннотации и паттерны не распознаются как отдельные сущности;
нет специальных обработчиков для @Transactional, Spring Security, Discount strategies и т.п.;
нет explain_architecture, explain_business_logic с осознанием слоёв/модулей.
Нет развитого набора MCP-инструментов
есть только index_project, project_query, search_code (поиск по чанкам);
отсутствуют: editor_context_query, explain_architecture, find_bugs, generate_tests, analyze_impact, find_error_source и т.д.;
нет реальной JSON‑RPC/MCP-обвязки — пока чистые Python‑функции.
RAG‑уровень ещё базовый
RagOrchestrator формирует простой текстовый контекст без реранкинга и без интеграции с LLM;
нет сценариев интерактивного уточнения запросов, фильтров по слоям/типам артефактов на уровне API.
Инфраструктура / UX
нет CLI/MCP‑launch‑скрипта, docker‑образа;
нет логирования индексации/запросов, нет конфиг‑файла;
нет минимальных тестов на ключевые шаги (scanner/parser/chunker/indexer).
Если хочешь продолжать по шагам, логичный следующий блок работы:
заполнение графа зависимостей + простой analyze_impact и explain_architecture поверх него.
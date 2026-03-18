# code-rag MCP tool

Модуль Retrieval-Augmented Generation (RAG) для Java-проектов.

Это Python-библиотека и MCP-сервер, который:
- индексирует структуру Java-проекта (Maven/Gradle, multi-module);
- строит семантические чанки кода (tree-sitter);
- строит граф зависимостей (class-level + method-level);
- выполняет семантический поиск и RAG-запросы через GigaChat Embeddings.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Настройка GigaChat Embeddings

Для семантического поиска используется [GigaChat API](https://developers.sber.ru/portal/products/gigachat).

1. Зарегистрируйтесь на [developers.sber.ru](https://developers.sber.ru/portal/products/gigachat)
2. Создайте проект, скопируйте **Authorization Key** (base64)
3. Задайте переменную окружения:

```bash
export GIGACHAT_AUTH_KEY="ваш_authorization_key"

# Опционально (по умолчанию GIGACHAT_API_PERS):
export GIGACHAT_SCOPE="GIGACHAT_API_PERS"

# Если нужно отключить проверку SSL (самоподписанный сертификат Sber):
export GIGACHAT_VERIFY_SSL=false
```

Без `GIGACHAT_AUTH_KEY` индексатор автоматически переключается на локальный детерминированный fallback (для тестов/разработки без API).

## Запуск MCP-сервера

```bash
# stdio транспорт (для Claude Desktop / Cursor / Continue)
python -m code_rag mcp
```

### Подключение к Claude Desktop

В `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "code-rag": {
      "command": "python",
      "args": ["-m", "code_rag", "mcp"],
      "cwd": "/path/to/vibe-code-rag",
      "env": {
        "GIGACHAT_AUTH_KEY": "ваш_ключ",
        "GIGACHAT_VERIFY_SSL": "false"
      }
    }
  }
}
```

## CLI-использование

### Граф зависимостей (`deps`)

Анализирует архитектуру Java-проекта без эмбеддингов — работает мгновенно.
Поддерживает Maven/Gradle, multi-module проекты, нестандартные структуры `src/`.

```bash
# Слоёная таблица (по умолчанию)
python -m code_rag deps /path/to/java-project

# Полное дерево: каждый класс со списком зависимостей
python -m code_rag deps /path/to/java-project --format full

# Mermaid-граф (для GitHub README / Obsidian)
python -m code_rag deps /path/to/java-project --format mermaid

# Все три формата сразу
python -m code_rag deps /path/to/java-project --format all

# Сохранить Markdown в корень проекта (DEPENDENCY_TREE.md)
python -m code_rag deps /path/to/java-project --export

# Сохранить под своим именем
python -m code_rag deps /path/to/java-project --export --output ARCH.md

# Экспорт сырых связей в CSV (для Excel / Gephi)
python -m code_rag deps /path/to/java-project --edges-csv edges.csv

# Экспорт в JSON (для своей визуализации / D3.js)
python -m code_rag deps /path/to/java-project --edges-json edges.json

# Всё сразу
python -m code_rag deps /path/to/java-project --export --edges-csv edges.csv --edges-json edges.json
```

**Что показывает вывод:**

- Таблица классов по архитектурным слоям (Controller / Servlet / Service / Repository / DTO / Entity / Enum / Exception / Config)
- Impl-классы свёрнуты под интерфейс: `AccountService _(+ impl)_`
- Ключевые потоки между слоями (Controller → Service → Repository)
- Второстепенные зависимости — в свёрнутом блоке `<details>`
- Архитектурные нарушения (`⚠️`): Config → Repository, DTO → Service и т.д.

**Результаты на реальных проектах:**

| Проект | Классов | Связей | Нарушений |
|--------|---------|--------|-----------|
| bike-rental-service | 39 | 66 | 0 |
| BankingPortal-API | 71 | 127 | 2 |
| mall (7 модулей) | 455 | 768 | 6 |
| Train-Ticket-Reservation-System | 55 | 103 | 0 |

### RAG-команды (требуют GIGACHAT_AUTH_KEY)

```bash
# Индексация проекта (первый раз ~30 сек, потом из кэша)
python -m code_rag index /path/to/java-project

# Семантический поиск
python -m code_rag project-query /path/to/java-project "user authentication flow"

# Текстовый поиск с фильтром
python -m code_rag search-code /path/to/java-project "@Transactional" --class-filter "*Service"
```

## MCP-инструменты

| Tool | Эмбеддинги | Описание |
|------|-----------|----------|
| `dependency_tree` | ❌ не нужны | Граф зависимостей, слои, нарушения архитектуры |
| `index_project_tool` | ✅ GigaChat | Индексирует Java-проект |
| `project_query_tool` | ✅ GigaChat | Семантический поиск по проекту |
| `search_code` | ❌ не нужны | Текстовый поиск по чанкам |
| `analyze_impact` | ✅ GigaChat | Анализ влияния изменения класса/метода |
| `find_usages` | ✅ GigaChat | Где используется класс/метод |
| `explain_architecture` | ✅ GigaChat | Архитектурное объяснение фичи |

## Структура проекта

- `code_rag/`
  - `project_scanner.py` — поиск модулей и исходников
  - `code_parser.py` — парсинг Java-кода (tree-sitter)
  - `chunker.py` — формирование семантических чанков
  - `dependency_graph.py` — граф зависимостей
  - `dependency_extractor.py` — извлечение типов и вызовов методов
  - `embedding_store.py` — InMemory и Chroma векторные сторы
  - `embeddings_client.py` — GigaChat OAuth2 клиент
  - `retriever.py` — семантический поиск
  - `rag_orchestrator.py` — RAG-пайплайн
  - `mcp_server.py` — MCP-сервер (FastMCP, stdio)
- `tests/` — pytest-тесты (22 теста)

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

```bash
# Индексация проекта
python -m code_rag index /path/to/java-project

# Семантический поиск
python -m code_rag project-query /path/to/java-project "user authentication flow"

# Текстовый поиск с фильтром
python -m code_rag search-code /path/to/java-project "@Transactional" --class-filter "*Service"
```

## MCP-инструменты

| Tool | Описание |
|------|----------|
| `index_project_tool` | Индексирует Java-проект |
| `project_query_tool` | Семантический поиск по проекту |
| `search_code` | Текстовый поиск по чанкам |
| `analyze_impact` | Анализ влияния изменения класса/метода |

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

# code-rag MCP tool

Модуль Retrieval-Augmented Generation (RAG) для Java-проектов.

Это Python-библиотека и MCP-сервер, который:
- индексирует структуру Java-проекта (Maven/Gradle, multi-module);
- строит семантические чанки кода;
- строит базовый граф зависимостей;
- выполняет семантический поиск и RAG-запросы.

## Установка

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Структура проекта (план)

- `code_rag/` — основной пакет:
  - `project_scanner.py` — поиск модулей и исходников;
  - `code_parser.py` — парсинг Java-кода (tree-sitter);
  - `chunker.py` — формирование семантических чанков;
  - `dependency_graph.py` — граф зависимостей;
  - `embedding_store.py` — работа с векторным стором;
  - `retriever.py` — комбинированный поиск;
  - `rag_orchestrator.py` — RAG-пайплайн;
  - `mcp_server.py` — экспозиция MCP-инструментов.


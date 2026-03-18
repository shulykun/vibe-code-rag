# code-rag lite — Java Dependency Tree via MCP

Облегчённый MCP-инструмент для визуализации архитектуры Java-проекта.

**Не требует:** эмбеддингов, GigaChat API, Qdrant, ChromaDB, numpy.  
**Работает:** мгновенно, только статический анализ AST через tree-sitter.

> Полная версия с семантическим поиском (RAG + GigaChat) — ветка [`master`](https://github.com/shulykun/vibe-code-rag/tree/master).

---

## Что умеет

Анализирует Java-проект и строит граф зависимостей между классами:

- Группирует по архитектурным слоям (Controller / Service / Repository / DTO / Exception)
- Показывает потоки между слоями
- Фильтрует внешние зависимости (JDK, Spring, Lombok и т.д.)
- Три формата вывода: таблица, полное дерево, Mermaid-граф

### Пример вывода (`--format layered`)

```
# Архитектурные слои: bike-rental-service

| Controller         | Service         | Repository         | DTO           |
| ---                | ---             | ---                | ---           |
| RentalController   | RentalService   | RentalRepository   | RentalResponse|
| BikeController     | BikeService     | BikeRepository     | BikeDto       |
| CustomerController | DiscountService | CustomerRepository | CustomerDto   |

## Потоки между слоями
- RentalService [Service] → RentalRepository [Repository]
- RentalService [Service] → DiscountService [Service]
- BikeController [Controller] → BikeService [Service]
```

---

## Установка

```bash
git clone -b lite/dependency-tree https://github.com/shulykun/vibe-code-rag
cd vibe-code-rag

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Зависимости** (всего 3):
```
tree-sitter==0.21.3
tree-sitter-languages==1.10.2
mcp
```

---

## CLI

```bash
# Таблица по слоям (по умолчанию)
python -m code_rag deps /path/to/java-project

# Полное дерево: каждый класс со списком зависимостей
python -m code_rag deps /path/to/java-project --format full

# Mermaid-граф (для GitHub README / Obsidian)
python -m code_rag deps /path/to/java-project --format mermaid

# Все три формата сразу
python -m code_rag deps /path/to/java-project --format all
```

---

## MCP-сервер

Запуск (stdio транспорт):

```bash
python -m code_rag mcp
```

### Подключение к Claude Desktop

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "code-rag-lite": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "code_rag", "mcp"],
      "cwd": "/path/to/vibe-code-rag"
    }
  }
}
```

### MCP-инструмент

**`dependency_tree`**

```
dependency_tree(root_path, format="layered")
```

| Параметр | Тип | Описание |
|----------|-----|----------|
| `root_path` | string | Путь к корню проекта (с `pom.xml` или `build.gradle`) |
| `format` | string | `layered` \| `full` \| `mermaid` \| `all` |

Возвращает:
```json
{
  "markdown": "# Архитектурные слои: ...",
  "stats": {
    "classes": 39,
    "edges": 66,
    "package_prefix": "com.bikerental",
    "layers": { "Controller": 4, "Service": 6, "Repository": 5 }
  }
}
```

---

## Поддерживаемые проекты

| Признак | Поддержка |
|---------|-----------|
| Maven (`pom.xml`) | ✅ |
| Gradle (`build.gradle`, `build.gradle.kts`) | ✅ |
| Multi-module | ✅ |
| Lombok (`@Data`, `@Builder` и т.д.) | ✅ корректно игнорируется |
| Кириллица в Javadoc | ✅ не ломает парсер |
| Kotlin | ❌ |

---

## Структура проекта

```
code_rag/
  __main__.py          — CLI (deps / mcp)
  mcp_server.py        — MCP-сервер (FastMCP, stdio)
  dep_graph_renderer.py — граф зависимостей и рендеринг
  dependency_extractor.py — извлечение типов и вызовов из AST
  dependency_graph.py  — структура графа
  code_parser.py       — парсинг Java через tree-sitter
  chunker.py           — чанки по классам/методам
  project_scanner.py   — поиск модулей и исходников
tests/                 — 22 pytest-теста
```

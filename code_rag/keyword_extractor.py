from __future__ import annotations

"""
Эвристическое извлечение смысловых ключевых слов из Java-кода.

Без LLM — только разбор текста. Извлекает:
- Enum-значения (BikeStatus.AVAILABLE, RentalStatus.COMPLETED)
- Строковые константы из кода
- Имена переменных в camelCase → слова (rentalId → rental, id)
- Spring/JPA аннотации как теги (@Transactional, @Cacheable)
- Имена исключений которые бросает метод (throw new BikeNotFoundException)
- Магические числа с контекстом (> 5 → limit check)

Цель: обогатить embed_text неявным смыслом кода без вызова LLM.
"""

import re
from typing import List, Set


# Аннотации которые несут смысловую нагрузку (не просто @Override)
_MEANINGFUL_ANNOTATIONS = {
    "Transactional", "Cacheable", "CacheEvict", "CachePut",
    "Scheduled", "Async", "EventListener",
    "PreAuthorize", "PostAuthorize", "Secured",
    "Valid", "Validated", "NotNull", "NotBlank",
    "Query", "Modifying", "Lock",
}

# Стоп-слова — слишком общие, не несут смысла
_STOP_WORDS = {
    "get", "set", "is", "has", "can", "do", "the", "this", "that",
    "new", "null", "true", "false", "return", "void", "int", "long",
    "string", "list", "map", "optional", "object", "class", "interface",
    "public", "private", "protected", "static", "final", "override",
    "import", "package", "extends", "implements", "super",
    "if", "else", "for", "while", "try", "catch", "throw", "throws",
    "log", "logger", "slf4j", "info", "debug", "warn", "error",
}


def extract_keywords(code: str) -> List[str]:
    """
    Извлекает смысловые ключевые слова из Java-кода метода/класса.

    Возвращает дедуплицированный список, отсортированный по значимости.
    """
    keywords: List[str] = []

    # 1. Enum-значения: SomeType.VALUE_NAME → "value name"
    for m in re.finditer(r'\b([A-Z][A-Za-z]+)\.([A-Z][A-Z_]+)\b', code):
        enum_class = m.group(1)
        enum_value = m.group(2).replace("_", " ").lower()
        keywords.append(f"{enum_class.lower()} {enum_value}")

    # 2. Аннотации: @Transactional, @Cacheable(...)
    for m in re.finditer(r'@(\w+)', code):
        ann = m.group(1)
        if ann in _MEANINGFUL_ANNOTATIONS:
            keywords.append(ann.lower())

    # 3. throw new XxxException → "xxx exception"
    for m in re.finditer(r'throw\s+new\s+(\w+Exception)\b', code):
        exc = _camel_to_words(m.group(1))
        keywords.append(exc)

    # 4. Строковые константы (короткие, осмысленные)
    for m in re.finditer(r'"([^"]{3,40})"', code):
        s = m.group(1).strip()
        if s and not s.startswith("http") and " " in s:
            # Только фразы (с пробелом), не технические строки
            keywords.append(s.lower())

    # 5. camelCase идентификаторы → слова
    # Ищем имена переменных/полей (после типов или в вызовах)
    for m in re.finditer(r'\b([a-z][a-zA-Z]{3,})\b', code):
        word = m.group(1)
        split = _camel_to_words(word)
        if len(split) > 1:  # только если реально camelCase разбился
            keywords.append(split)

    # 6. Числовые константы с контекстом
    # > N, == N, % N — часто означают бизнес-правила
    for m in re.finditer(r'[><%=!]+\s*(\d+)\b', code):
        n = m.group(1)
        if 1 < int(n) < 1000:  # исключаем 0, 1 и слишком большие
            context = code[max(0, m.start()-20):m.end()].strip()
            keywords.append(f"limit {n}")

    # Дедупликация с сохранением порядка
    seen: Set[str] = set()
    result: List[str] = []
    for kw in keywords:
        kw = kw.strip()
        if not kw or kw in seen:
            continue
        words = kw.lower().split()
        # Фильтруем стоп-слова (оставляем фразы где хотя бы одно слово значимое)
        meaningful = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
        if not meaningful:
            continue
        seen.add(kw)
        result.append(kw)

    return result[:20]  # не больше 20 keywords


def _camel_to_words(name: str) -> str:
    """
    RentalService → rental service
    calculateBonusPoints → calculate bonus points
    BikeNotAvailableException → bike not available exception
    """
    # Вставляем пробел перед каждой заглавной после строчной
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # И перед заглавной перед строчной (ABC → A B C → но ABCService → ABC service)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s)
    return s.lower()


def format_keywords_for_embed(keywords: List[str]) -> str:
    """Форматирует ключевые слова для добавления в embed_text."""
    if not keywords:
        return ""
    return "// Keywords: " + ", ".join(keywords)


__all__ = ["extract_keywords", "format_keywords_for_embed"]

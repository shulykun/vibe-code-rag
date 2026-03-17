# Требования к Java-проекту для работы с code-rag

Документ описывает что нужно сделать в Java-проекте чтобы семантический поиск работал хорошо.

---

## 1. Структура проекта

### ✅ Поддерживается
- Maven (наличие `pom.xml` в корне)
- Gradle (наличие `build.gradle` или `build.gradle.kts`)
- Multi-module проекты (каждый модуль сканируется отдельно)

### ✅ Расположение исходников
Стандартные пути сканируются автоматически:
```
src/main/java/   — основной код
src/test/java/   — тестовый код
```

---

## 2. Javadoc — главный инструмент релевантности

RAG читает Javadoc и добавляет его в текст эмбеддинга. **Это самое важное**.

### ✅ Что писать

Пишите Javadoc на классах и публичных методах с бизнес-смыслом:

```java
/**
 * Сервис управления арендой велосипедов.
 *
 * Правила:
 * - Один клиент — одна активная аренда.
 * - При просрочке начисляется штраф 50 руб/час.
 */
@Service
public class RentalService { ... }

/**
 * Возвращает велосипед и закрывает аренду.
 * Рассчитывает итоговую стоимость и начисляет бонусные баллы.
 *
 * @throws ResourceNotFoundException если аренда не найдена
 * @throws IllegalStateException если аренда уже закрыта
 */
@Transactional
public RentalResponse returnBike(Long rentalId) { ... }
```

### ❌ Чего избегать

```java
/** Возвращает велосипед. */         // слишком коротко — бесполезно
public RentalResponse returnBike() {}

// Комментарий-разделитель            // ломает AST-парсер!
// ── Private methods ──────────────────────────────────────────────────
```

> ⚠️ **Важно:** длинные строки с Unicode-символами (`─`, `═`, `•`) в комментариях
> ломают tree-sitter AST-парсер и приводят к неправильному извлечению имён методов.
> Используйте обычные ASCII-разделители: `// --- Private methods ---`

---

## 3. Именование

RAG строит embed_text из имени класса и метода — хорошие имена напрямую влияют на поиск.

### ✅ Хорошо
```java
public class DiscountService { ... }
public boolean isDiscountApplicable(Long customerId) { ... }
public BigDecimal calculateLateFee(Rental rental) { ... }
```

### ❌ Плохо
```java
public class Mgr { ... }           // непонятное сокращение
public boolean check(Long id) {}   // что проверяет?
public BigDecimal calc() {}        // что считает?
```

---

## 4. Кириллица и многоязычность

**Кириллица в Javadoc — работает и помогает** при русскоязычных запросах:

```java
/**
 * Начисляет бонусные баллы: 1 балл за каждые 60 минут аренды.
 */
public int calculateBonusPoints(Duration actualDuration) { ... }
```

> Запрос "где начисляются бонусные баллы" найдёт этот метод корректно.

**Кириллица в именах классов/методов — НЕ поддерживается** (Java не разрешает).

---

## 5. Размер методов

RAG работает на уровне методов. Оптимальный размер:

| Размер | Результат |
|--------|-----------|
| 5–50 строк | ✅ Идеально — чанк содержательный |
| 51–100 строк | ✅ Допустимо |
| >100 строк | ⚠️ Чанк обрезается до 2000 символов — часть кода не попадёт в эмбеддинг |

> **Совет:** длинные методы всё равно стоит рефакторить по принципу SRP — это хорошо и для RAG, и для кода.

---

## 6. Разделение по слоям

Чем чище архитектурное разделение — тем лучше RAG понимает "кто за что отвечает":

```
controller/   — HTTP-эндпоинты
service/      — бизнес-логика (здесь важнее всего Javadoc)
repository/   — доступ к данным
model/        — сущности
dto/          — объекты запроса/ответа
exception/    — исключения
```

RAG использует имя файла и класса как контекст — `RentalService.returnBike` даёт
гораздо больше информации чем `S1.m2`.

---

## 7. Чего RAG пока не понимает

| Ограничение | Статус |
|-------------|--------|
| Lombok-аннотации (`@Builder`, `@Data`) | Игнорируются в AST, но код работает |
| `obj.method()` через поле (без типизации) | Граф вызовов — best-effort |
| Generics в сигнатурах | Парсятся корректно |
| Spring AOP / прокси | Не анализируются |
| Kotlin | Не поддерживается |

---

## 8. Быстрая проверка

Проверьте что ваш проект готов к индексации:

```bash
# Должен найти pom.xml или build.gradle
ls pom.xml build.gradle 2>/dev/null

# Должны быть Java-файлы в стандартных путях
find src/main/java -name "*.java" | wc -l

# Нет Unicode-разделителей в комментариях
grep -rn "──\|══\|━━" src/main/java/ && echo "WARNING: Unicode separators found"
```

```bash
# Индексация (из директории vibe-code-rag)
export GIGACHAT_AUTH_KEY="..."
export GIGACHAT_VERIFY_SSL=false
python -m code_rag index /path/to/your/java/project
```

---

## 9. Пример хорошо оформленного сервиса

```java
package com.example.payment;

import ...

/**
 * Сервис обработки платежей.
 *
 * Поддерживает оплату картой и через СБП.
 * Все транзакции логируются в AuditService.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaymentService {

    private final PaymentRepository paymentRepository;
    private final AuditService auditService;

    /**
     * Выполняет оплату заказа.
     * При неудаче выбрасывает PaymentException с кодом ошибки от провайдера.
     *
     * @param orderId идентификатор заказа
     * @param amount  сумма в рублях
     * @return результат транзакции
     */
    @Transactional
    public PaymentResult processPayment(String orderId, BigDecimal amount) {
        // ...
    }

    /**
     * Возвращает средства по идентификатору транзакции.
     */
    @Transactional
    public void refund(String transactionId) {
        // ...
    }
}
```

Такой класс RAG найдёт по запросам:
- "как работает оплата заказа"
- "возврат средств refund"
- "PaymentService processPayment"

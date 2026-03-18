Типичные запросы к MCP-серверу

1. Поиск и анализ кода

Запрос: "Найди все места, где мы используем @Transactional в сервисном слое"

json
{
  "tool": "search_code",
  "arguments": {
    "query": "@Transactional annotation in service layer classes",
    "class_filter": "*Service",
    "limit": 20
  }
}
Что вернет MCP:

json
[
  {
    "class": "com.company.order.OrderService",
    "method": "createOrder",
    "annotation": "@Transactional(propagation=REQUIRED)",
    "code_snippet": "@Override\n@Transactional\npublic Order createOrder(OrderDto dto) { ... }",
    "context": "Вызывается из OrderController, использует OrderRepository"
  },
  {
    "class": "com.company.payment.PaymentService", 
    "method": "processRefund",
    "annotation": "@Transactional(rollbackFor = Exception.class)",
    "code_snippet": "@Transactional(rollbackFor = {PaymentException.class})\npublic void processRefund(String paymentId) { ... }",
    "context": "Использует PaymentGateway, логгирует в AuditService"
  }
]
2. Понимание архитектуры

Запрос: "Объясни, как у нас работает аутентификация. Покажи цепочку вызовов от контроллера до БД"

json
{
  "tool": "explain_architecture",
  "arguments": {
    "feature": "authentication",
    "detail_level": "full_call_chain"
  }
}
Ответ MCP:

text
В проекте используется JWT-аутентификация через Spring Security:

1. Контроллер: AuthController.login()
   - Принимает LoginRequest (email/password)
   - Вызывает AuthenticationManager.authenticate()

2. Сервис: CustomUserDetailsService implements UserDetailsService
   - loadUserByUsername() → UserRepository.findByEmail()
   
3. Фильтры: JwtAuthenticationFilter (до Spring Security)
   - Извлекает JWT из заголовка Authorization
   - Проверяет валидность через JwtService
   - Устанавливает SecurityContextHolder

4. Конфигурация: SecurityConfig
   - Настраивает цепочку фильтров
   - Разрешает public endpoints: /api/auth/**, /health
   - Требует аутентификацию для /api/**

Вот граф зависимостей:
[AuthController] → [AuthenticationManager] → [UserDetailsService]
                                           → [PasswordEncoder]
                                           → [JwtService]
3. Рефакторинг с учетом существующих паттернов

Запрос: "Перепиши этот класс в стиле существующих репозиториев"

json
{
  "tool": "refactor_with_pattern",
  "arguments": {
    "file_path": "src/main/java/com/company/product/NewProductRepository.java",
    "pattern_name": "repository",
    "reference_class": "com.company.user.UserRepository"
  }
}
MCP анализирует UserRepository:

java
// Анализ эталона
@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);
    boolean existsByEmail(String email);
    
    @Query("SELECT u FROM User u WHERE u.status = :status")
    List<User> findAllByStatus(@Param("status") UserStatus status);
}
Генерирует для ProductRepository:

java
@Repository
public interface ProductRepository extends JpaRepository<Product, Long> {
    Optional<Product> findBySku(String sku);  // по аналогии с email
    boolean existsBySku(String sku);
    
    @Query("SELECT p FROM Product p WHERE p.category = :category")
    List<Product> findAllByCategory(@Param("category") Category category);
    
    // Дополнительно: находит все похожие паттерны в проекте
    // и предлагает добавить пагинацию, как в OrderRepository
    @Query("SELECT p FROM Product p WHERE p.price BETWEEN :min AND :max")
    Page<Product> findByPriceRange(@Param("min") BigDecimal min, 
                                   @Param("max") BigDecimal max,
                                   Pageable pageable);
}
4. Поиск багов и проблемных мест

Запрос: "Найди потенциальные NPE в этом методе"

json
{
  "tool": "find_bugs",
  "arguments": {
    "file_path": "src/main/java/com/company/order/OrderProcessor.java",
    "method_name": "processOrder",
    "bug_patterns": ["null_pointer", "resource_leak"]
  }
}
Анализ MCP:

text
Анализ метода OrderProcessor.processOrder(Order order):

⚠️ Потенциальные проблемы:

1. Строка 45: order.getItems() может быть null
   - В проекте есть @NotNull аннотация на поле items, 
     но проверка на null отсутствует
   - Решение: добавить проверку или использовать Collections.emptyList()

2. Строка 52: paymentService.process(order.getPaymentDetails())
   - paymentDetails может быть null для бесплатных заказов
   - В других сервисах используется Optional<PaymentDetails>

3. Строка 60: try-with-resources не используется для FileWriter
   - Ресурс может не закрыться при исключении
   - В проекте принято использовать try-with-resources (см. FileService.java:120)

🔍 Нашел похожий баг, который уже фиксили в UserService:
   - Коммит abc123: "Fix NPE in UserService.updateProfile"
   - Рекомендуемый паттерн: использовать Objects.requireNonNull()
5. Тестирование и качество кода

Запрос: "Сгенерируй тесты для этого класса в стиле проекта"

json
{
  "tool": "generate_tests",
  "arguments": {
    "class_name": "com.company.product.ProductService",
    "test_style": "mockito",
    "coverage_target": "branch"
  }
}
MCP находит типичные тесты в проекте:

java
// Анализирует ProductServiceTest.java (если есть)
// Или анализирует стиль тестов в других сервисах

@ExtendWith(MockitoExtension.class)
class ProductServiceTest {
    @Mock
    private ProductRepository productRepository;
    
    @Mock
    private AuditService auditService;
    
    @InjectMocks
    private ProductService productService;
    
    @Test
    void shouldCreateProduct_WhenValidData() {
        // given - типичный паттерн given/when/then из проекта
        ProductDto dto = new ProductDto("SKU123", "Test Product", BigDecimal.TEN);
        when(productRepository.save(any(Product.class))).thenAnswer(i -> i.getArgument(0));
        
        // when
        Product result = productService.createProduct(dto);
        
        // then
        assertThat(result.getSku()).isEqualTo("SKU123");
        verify(auditService).log(any());
    }
    
    @Test
    void shouldThrowException_WhenProductExists() {
        // given
        String sku = "EXISTING_SKU";
        when(productRepository.existsBySku(sku)).thenReturn(true);
        
        // when/then
        assertThatThrownBy(() -> productService.findBySku(sku))
            .isInstanceOf(ProductNotFoundException.class)
            .hasMessageContaining(sku);
    }
}
6. Анализ влияния (Impact Analysis)

Запрос: "Что сломается, если я изменю сигнатуру метода createOrder?"

json
{
  "tool": "analyze_impact",
  "arguments": {
    "class_name": "com.company.order.OrderService",
    "method_name": "createOrder",
    "change_type": "signature_change",
    "new_signature": "createOrder(OrderDto dto, UserContext context)"
  }
}
MCP анализирует:

text
🔍 Анализ влияния изменения OrderService.createOrder(OrderDto)

Прямые вызовы (7 мест):
1. OrderController.createOrder (строка 42)
2. OrderBatchProcessor.processBatch (строка 156)
3. OrderImportService.importFromLegacy (строка 89)
4. TestOrderFactory.createTestOrder (тестовый класс)
5. OrderWebService.createOrder (SOAP эндпоинт)
6. OrderRestClient (в интеграционных тестах)
7. OrderServiceTest (3 тестовых метода)

Транзитивные вызовы (через цепочку):
- OrderController.createOrder → вызывается из:
  * Frontend (React) через /api/orders
  * Mobile app через API gateway
  * Admin panel (ручное создание)

Покрытие тестами:
- ✅ 8 юнит-тестов падают
- ✅ 3 интеграционных теста
- ❌ 2 теста в модуле payment (могут быть не связаны)

Рекомендации:
1. Создать перегрузку с новой сигнатурой (не ломать API)
2. Поэтапно мигрировать: сначала @Deprecated старую версию
3. Обновить тесты: найденные 11 тестов требуют изменений
7. Поиск по ошибкам и stacktrace

Запрос: "Найди, где в коде может возникать эта ошибка: NullPointerException при вызове getUser().getEmail()"

json
{
  "tool": "find_error_source",
  "arguments": {
    "stacktrace_sample": "java.lang.NullPointerException: Cannot invoke \"com.company.model.User.getEmail()\" because the return value of \"com.company.service.AuthService.getCurrentUser()\" is null",
    "search_depth": "deep"
  }
}
MCP находит:

text
🔎 Анализ ошибки: NPE в AuthService.getCurrentUser().getEmail()

Найдено 5 мест с похожим паттерном:

1. EmailNotificationService.java:87
   String email = authService.getCurrentUser().getEmail();
   - Нет проверки на null
   - Метод getCurrentUser() может вернуть null (см. JavaDoc)
   
2. UserProfileController.java:42
   return ResponseEntity.ok(userService.getUserProfile(
       authService.getCurrentUser().getId()  // потенциальный NPE
   ));
   
3. AuditAspect.java:156 (аспект логгирования)
   log.info("User: {}", authService.getCurrentUser().getUsername());

4. SecurityUtils.java (в проекте есть хелпер):
   public static User getCurrentUser() {
       return Optional.ofNullable(SecurityContextHolder.getContext()
           .getAuthentication())
           .map(Authentication::getPrincipal)
           .map(User.class::cast)
           .orElse(null);  // Вот почему возвращается null!
   }

Решение из проекта (найдено в UserController.java):
   User user = authService.getCurrentUser();
   if (user == null) {
       throw new UnauthorizedException("User not authenticated");
   }
   String email = user.getEmail();
8. Понимание бизнес-логики

Запрос: "Объясни, как работает расчет скидки в нашем проекте"

json
{
  "tool": "explain_business_logic",
  "arguments": {
    "domain": "discount",
    "include_rules": true
  }
}
MCP агрегирует знания:

text
🧮 Система расчета скидок в проекте:

Архитектура: Strategy Pattern
- Интерфейс: DiscountStrategy (в модуле pricing)
- Реализации:
  1. VolumeDiscountStrategy (скидка за объем)
  2. LoyaltyDiscountStrategy (постоянные клиенты)
  3. PromoCodeStrategy (промокоды)
  4. SeasonalDiscountStrategy (сезонные)

Бизнес-правила (из кода + JavaDoc):
1. Скидки комбинируются, но не более 30% (класс DiscountCalculator.java:45)
2. Loyalty скидка применяется первой (порядок в DiscountChain.java)
3. Промокоды не работают с товарами из категории "PREMIUM"

Пример расчета (из тестов):
   Order: 3 товара по 1000 руб
   Volume: 5% (т.к. >2 товаров)
   Loyalty: 10% (Gold статус)
   Итог: 1000*3 * (1 - 0.05) * (1 - 0.10) = 2565 руб

Где используется:
- CartController.calculateTotal()
- OrderProcessor.applyDiscounts()
- PricingService.getBestPrice()

Последние изменения:
- Git blame показывает, что правила комбинации меняли в марте
- Связанный тикет: PROD-2345 "Fix discount stacking order"
Форматы ответов MCP

MCP может возвращать данные в разных форматах, которые клиент (IDE) умеет отображать:

Markdown с подсветкой кода (для объяснений)
JSON (для структурированных данных)
Ссылки на файлы (можно открыть в IDE)
Diff-формат (для предложений изменений)
Графы (визуализация зависимостей)
Как это выглядит в IDE

В Continue или Cursor разработчик просто пишет:

text
@java-rag найди все места с @Transactional без rollbackFor
И MCP-сервер возвращает структурированный ответ с возможностью:

Перейти к файлу (кликабельно)
Применить предложенное изменение (если это рефакторинг)
Посмотреть контекст (другие связанные классы)
Хочешь, я покажу, как настроить конкретный тип запроса или добавить новый инструмент в MCP-сервер?
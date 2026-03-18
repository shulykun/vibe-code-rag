Сделано: “кто кого вызывает” (best‑effort) + impact по методу
Мы дополнили пункт из next.md (2–5): теперь извлекаем связи вызовов методов (ограниченно, но уже полезно) и умеем analyze_impact для конкретного метода.
Что изменилось
chunker.py
Для method‑чанков добавляем metadata["class"] (имя текущего класса), чтобы в ответах/поиске было меньше “приблизительности”.
dependency_extractor.py
Добавлена функция extract_method_calls(...), которая строит best‑effort вызовы:
CurrentFQCN#method -> CurrentFQCN#otherMethod для вызовов вида method()
CurrentFQCN#method -> ResolvedType#method для вызовов вида Type.method()
Важно: obj.method() пока не резолвим (без типизации receiver-а).
indexer.py
При индексации теперь добавляем рёбра:
uses (как раньше) на уровне классов
calls на уровне методов Class#method
mcp_server.py
mcp_analyze_impact теперь принимает method_name: Optional[str]:
если задан — анализирует узел Class#method
если нет — как раньше по классу
Как пользоваться
Impact по классу:
mcp_analyze_impact(root_path, class_name="com.company.order.OrderService")
Impact по методу:
mcp_analyze_impact(  root_path,  class_name="com.company.order.OrderService",  method_name="createOrder",  max_depth=3)
Следующий логичный апгрейд, чтобы приблизиться к юз‑кейсам: научиться обрабатывать obj.method() через простую резолюцию по полям/параметрам (хотя бы внутри класса)
"""
Spanish language strings for architect-cli.

Must have the same keys as en.py.
"""

STRINGS: dict[str, str] = {
    # ── Human Formatter: LLM ────────────────────────────────────────────
    "human.llm_call": "\n🔄 Paso {step} → Llamada al LLM ({messages} mensajes)",
    "human.llm_response_tools": "   ✓ LLM respondió con {count} tool call{s}",
    "human.llm_response_text": "   ✓ LLM respondió con texto final",
    "human.agent_complete": (
        "\n✅ Agente completado ({steps} pasos)\n"
        "   Razón: LLM decidió que terminó{cost_line}"
    ),
    "human.cost_line": "\n   Coste: {cost}",
    # ── Human Formatter: Tools ──────────────────────────────────────────
    "human.tool_call": "\n   🔧 {tool} → {summary}",
    "human.tool_call_mcp": "\n   🌐 {tool} → {summary}  (MCP: {server})",
    "human.tool_ok": "      ✓ OK",
    "human.tool_error": "      ✗ ERROR: {error}",
    "human.hook_complete": "      🔍 Hook {hook}: {icon}",
    "human.hooks_executed": "      🔍 hooks ejecutados",
    # ── Human Formatter: Safety nets ────────────────────────────────────
    "human.user_interrupt": "\n⚠️  Interrumpido por el usuario",
    "human.max_steps": (
        "\n⚠️  Límite de pasos alcanzado ({step}/{max_steps})\n"
        "    Pidiendo al agente que resuma..."
    ),
    "human.budget_exceeded": (
        "\n⚠️  Presupuesto excedido (${spent}/{budget})\n"
        "    Pidiendo al agente que resuma..."
    ),
    "human.timeout": "\n⚠️  Timeout alcanzado\n    Pidiendo al agente que resuma...",
    "human.context_full": "\n⚠️  Contexto lleno\n    Pidiendo al agente que resuma...",
    # ── Human Formatter: LLM errors ─────────────────────────────────────
    "human.llm_error": "\n❌ Error del LLM: {error}",
    "human.step_timeout": "\n⚠️  Step timeout ({seconds}s)\n    Pidiendo al agente que resuma...",
    # ── Human Formatter: Agent lifecycle ─────────────────────────────────
    "human.closing": "\n🔄 Cerrando ({reason}, {steps} pasos completados)",
    "human.loop_complete_success": "  ({steps} pasos, {tool_calls} tool calls){cost_line}",
    "human.loop_complete_stopped": "\n⚡ Detenido ({status}{reason_str}, {steps} pasos){cost_line}",
    # ── Human Formatter: Pipeline ───────────────────────────────────────
    "human.pipeline_step_skipped": "\n   ⏭️  Step '{step}' omitido (condición no cumplida)",
    "human.pipeline_step_done": "\n   {icon} Step '{step}' → {status} ({cost_str}, {dur_str})",
    # ── Human Formatter: Ralph Loop ─────────────────────────────────────
    "human.ralph_checks": "   🧪 Checks: {passed}/{total} passed{check_icon}",
    "human.ralph_iteration_done": "   {icon} Iteration {iteration} → {status} ({cost_str}, {dur_str})",
    "human.ralph_complete": "\n{icon} Ralph complete — {total_iterations} iterations, {status} ({cost_str})",
    # ── Human Formatter: Auto-Reviewer ──────────────────────────────────
    "human.reviewer_start_label": " Auto-Review ({diff_lines} líneas de diff) ",
    "human.reviewer_complete": "   {icon} Review completo: {status}, {issues} issues, score {score}",
    "human.reviewer_status_approved": "aprobado",
    "human.reviewer_status_rejected": "no aprobado",
    # ── Human Formatter: Parallel Runs ──────────────────────────────────
    "human.parallel_worker_done": "   {icon} Worker {worker} ({model}) → {status} ({cost_str}, {dur_str})",
    "human.parallel_worker_error": "   ✗ Worker {worker} → error: {error}",
    "human.parallel_complete": (
        "\n⚡ Parallel complete — {total_workers} workers: "
        "{succeeded} success, {failed} failed ({cost_str})"
    ),
    # ── Human Formatter: Competitive Eval ───────────────────────────────
    "human.competitive_ranking_empty": "\n🏁 Ranking final: (sin resultados)",
    "human.competitive_ranking": "\n🏁 Ranking final: {ranking}",
    # ── Human Formatter: Context ────────────────────────────────────────
    "human.context_compressing": "   📦 Comprimiendo contexto — {exchanges} intercambios",
    "human.context_window_enforced": "   📦 Ventana de contexto: eliminados {removed} mensajes antiguos",
    # ── Human Formatter: _summarize_args ────────────────────────────────
    "human.summary_lines": "{path} ({lines} líneas)",
    "human.summary_edit": "{path} ({old}→{new} líneas)",
    "human.summary_search": "\"{pattern}\" en {path}",
    "human.summary_no_args": "(sin args)",
    # ── Agent Prompts ───────────────────────────────────────────────────
    "prompt.build": (
        "Eres un agente de desarrollo de software. Trabajas de forma metódica y verificas tu trabajo.\n\n"
        "## Tu proceso de trabajo\n\n"
        "1. ANALIZAR: Lee los archivos relevantes y entiende el contexto antes de actuar\n"
        "2. PLANIFICAR: Piensa en los pasos necesarios y el orden correcto\n"
        "3. EJECUTAR: Haz los cambios paso a paso\n"
        "4. VERIFICAR: Después de cada cambio, comprueba que funciona\n"
        "5. CORREGIR: Si algo falla, analiza el error y corrígelo\n\n"
        "## Herramientas de edición — Jerarquía\n\n"
        "| Situación | Herramienta |\n"
        "|-----------|-------------|\n"
        "| Modificar un único bloque contiguo | `edit_file` (str_replace) ← **PREFERIR** |\n"
        "| Cambios en múltiples secciones | `apply_patch` (unified diff) |\n"
        "| Archivo nuevo o reescritura total | `write_file` |\n\n"
        "## Herramientas de búsqueda\n\n"
        "Antes de abrir archivos, usa estas herramientas para encontrar lo relevante:\n\n"
        "| Necesidad | Herramienta |\n"
        "|-----------|-------------|\n"
        "| Buscar definiciones, imports, código | `search_code` (regex) |\n"
        "| Buscar texto literal exacto | `grep` |\n"
        "| Localizar archivos por nombre | `find_files` |\n"
        "| Explorar un directorio | `list_files` |\n\n"
        "## Ejecución de comandos\n\n"
        "Usa `run_command` para verificar y ejecutar:\n\n"
        "| Situación | Ejemplo |\n"
        "|-----------|--------|\n"
        "| Ejecutar tests | `run_command(command=\"pytest tests/ -v\")` |\n"
        "| Verificar tipos | `run_command(command=\"mypy src/\")` |\n"
        "| Linting | `run_command(command=\"ruff check .\")` |\n\n"
        "## Reglas\n\n"
        "- Siempre lee un archivo antes de editarlo\n"
        "- Usa `search_code` o `grep` para encontrar código relevante en vez de adivinar\n"
        "- Si un comando o test falla, analiza el error e intenta corregirlo\n"
        "- NO pidas confirmación ni hagas preguntas — actúa con la información disponible\n"
        "- Cuando hayas completado la tarea, explica qué hiciste y qué archivos cambiaste\n"
        "- Haz el mínimo de cambios necesarios para completar la tarea"
    ),
    "prompt.plan": (
        "Eres un agente de análisis y planificación. Tu trabajo es entender una tarea\n"
        "y producir un plan detallado SIN ejecutar cambios.\n\n"
        "## Tu proceso\n\n"
        "1. Lee los archivos relevantes para entender el contexto\n"
        "2. Analiza qué cambios son necesarios\n"
        "3. Produce un plan estructurado con:\n"
        "   - Qué archivos hay que crear/modificar/borrar\n"
        "   - Qué cambios concretos en cada archivo\n"
        "   - En qué orden hacerlos\n"
        "   - Posibles riesgos o dependencias\n\n"
        "## Herramientas de exploración\n\n"
        "| Situación | Herramienta |\n"
        "|-----------|-------------|\n"
        "| Buscar definiciones, imports, código | `search_code` (regex) |\n"
        "| Buscar texto literal exacto | `grep` |\n"
        "| Localizar archivos por nombre | `find_files` |\n"
        "| Listar un directorio | `list_files` |\n"
        "| Leer contenido | `read_file` |\n\n"
        "## Reglas\n\n"
        "- NO modifiques ningún archivo\n"
        "- Usa las herramientas de búsqueda para investigar antes de planificar\n"
        "- Sé específico: no digas \"modificar auth.py\", di \"en auth.py, añadir validación\n"
        "  de token en la función validate() línea ~45\"\n"
        "- Si algo es ambiguo, indica las opciones y recomienda una"
    ),
    "prompt.resume": (
        "Eres un agente de análisis y resumen. Tu trabajo es leer información\n"
        "y producir un resumen claro y conciso. No modificas archivos.\n\n"
        "Sé directo. No repitas lo que ya sabe el usuario. Céntrate en lo importante."
    ),
    "prompt.review": (
        "Eres un agente de revisión de código. Tu trabajo es inspeccionar código\n"
        "y dar feedback constructivo y accionable.\n\n"
        "## Qué buscar\n\n"
        "- Bugs y errores lógicos\n"
        "- Problemas de seguridad\n"
        "- Oportunidades de simplificación\n"
        "- Code smells y violaciones de principios SOLID\n"
        "- Tests que faltan\n\n"
        "## Reglas\n\n"
        "- NO modifiques ningún archivo\n"
        "- Sé específico: indica archivo, línea y el problema concreto\n"
        "- Prioriza: primero bugs/seguridad, luego mejoras, luego estilo"
    ),
    "prompt.review_system": (
        "Eres un reviewer senior de código. Tu trabajo es revisar "
        "cambios de código hechos por otro agente y encontrar problemas.\n\n"
        "Busca específicamente:\n"
        "1. Bugs lógicos y edge cases no cubiertos\n"
        "2. Problemas de seguridad (SQL injection, XSS, secrets hardcoded, etc.)\n"
        "3. Violaciones de las convenciones del proyecto (si hay .architect.md, síguelo)\n"
        "4. Oportunidades de simplificación o mejora\n"
        "5. Tests faltantes o insuficientes\n\n"
        "Sé específico: indica archivo, línea, y qué cambio exacto harías.\n"
        "Si no encuentras problemas significativos, di \"Sin issues encontrados.\""
    ),
    # ── Close Instructions ──────────────────────────────────────────────
    "close.max_steps": (
        "Has alcanzado el límite máximo de pasos permitidos. "
        "Responde con un resumen de lo que completaste, qué queda pendiente "
        "y sugerencias para continuar en otra sesión."
    ),
    "close.budget_exceeded": (
        "Se ha alcanzado el presupuesto máximo de coste. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
    "close.context_full": (
        "El contexto de conversación está lleno. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
    "close.agent_stopped": (
        "El agente se detuvo ({reason}). Pasos completados: {steps}."
    ),
    "close.timeout": (
        "Se agotó el tiempo asignado para esta ejecución. "
        "Resume brevemente lo que completaste y qué falta por hacer."
    ),
    # ── Evaluator ───────────────────────────────────────────────────────
    "eval.system_prompt": (
        "Eres un evaluador de resultados de agentes de IA. "
        "Tu trabajo es verificar si una tarea se completó correctamente.\n\n"
        "IMPORTANTE: Responde ÚNICAMENTE con un JSON válido con esta estructura exacta:\n"
        '{"completed": true_o_false, "confidence": número_entre_0_y_1, '
        '"issues": ["lista", "de", "problemas"], "suggestion": "sugerencia_de_mejora"}\n\n'
        "- completed: true si la tarea se realizó completa y correctamente\n"
        "- confidence: tu nivel de seguridad (1.0 = totalmente seguro)\n"
        "- issues: lista vacía [] si todo está bien; lista de problemas si no\n"
        "- suggestion: qué debería hacer el agente para mejorar (vacío si completed=true)\n\n"
        "No incluyas explicaciones ni texto fuera del JSON."
    ),
    "eval.user_prompt": (
        "**Tarea original del usuario:**\n{original_prompt}\n\n"
        "**Resultado del agente:**\n{output_preview}\n\n"
        "**Acciones ejecutadas:**\n{steps_summary}\n\n"
        "¿La tarea se completó correctamente?"
    ),
    "eval.no_output": "(sin output)",
    "eval.error": "Error al evaluar: {error}",
    "eval.error_suggestion": "Verifica el resultado manualmente.",
    "eval.parse_failed": "No se pudo parsear la evaluación del LLM.",
    "eval.parse_failed_suggestion": "Revisa manualmente el resultado.",
    "eval.no_steps": "(ningún paso ejecutado)",
    "eval.step_line": "  Paso {step}: {tools} [{status}]",
    "eval.step_no_tools": "  Paso {step}: (razonamiento sin tool calls)",
    "eval.status_ok": "OK",
    "eval.status_errors": "algunos errores",
    "eval.correction_prompt": (
        "La tarea anterior no se completó correctamente.\n\n"
        "**Tarea original:**\n{original_prompt}\n\n"
        "**Problemas detectados:**\n{issues_text}\n\n"
        "**Sugerencia:**\n{suggestion_text}\n\n"
        "Por favor, corrige estos problemas y completa la tarea correctamente."
    ),
    "eval.correction_default_issues": "  - Resultado incompleto o incorrecto.",
    "eval.correction_default_suggestion": "Revisa el resultado y completa la tarea.",
    # ── Context Manager ─────────────────────────────────────────────────
    "context.chars_omitted": "[... {n} caracteres omitidos ...]",
    "context.lines_omitted": "[... {n} líneas omitidas ...]",
    "context.summary_prompt": (
        "Resume de forma concisa las siguientes acciones del agente. "
        "Conserva detalles importantes (archivos modificados, decisiones clave). "
        "Omite detalles repetitivos:\n\n{content}"
    ),
    "context.summary_header": "[Resumen de pasos anteriores]",
    "context.mechanical_summary": "[Resumen mecánico — LLM no disponible]\n{content}",
    "context.agent_called_tools": "Agente llamó tools: {tools}",
    "context.agent_responded": "Agente respondió: {content}",
    "context.tool_result": "Resultado de {name}: {content}",
    "context.no_messages": "(sin mensajes)",
    # ── Guardrails ──────────────────────────────────────────────────────
    "guardrail.sensitive_blocked": (
        "Archivo sensible bloqueado por guardrail: {file} (patrón: {pattern})"
    ),
    "guardrail.protected_blocked": (
        "Archivo protegido por guardrail: {file} (patrón: {pattern})"
    ),
    "guardrail.command_blocked": (
        "Comando bloqueado por guardrail: coincide con '{pattern}'"
    ),
    "guardrail.command_write_blocked": (
        "Comando bloqueado: intenta escribir en archivo protegido "
        "'{target}' (patrón: {pattern})"
    ),
    "guardrail.command_read_blocked": (
        "Comando bloqueado: intenta leer archivo sensible "
        "'{target}' (patrón: {pattern})"
    ),
    "guardrail.commands_limit": (
        "Límite de comandos alcanzado ({limit}). "
        "El guardrail impide ejecutar más comandos."
    ),
    "guardrail.files_limit": (
        "Límite de archivos modificados alcanzado ({limit}). "
        "El guardrail impide modificar más archivos."
    ),
    "guardrail.lines_limit": (
        "Límite de líneas modificadas alcanzado ({limit}). "
        "El guardrail impide más ediciones."
    ),
    "guardrail.code_rule": (
        "Violación de regla de código en {file}: patrón '{pattern}' — {message}"
    ),
    "guardrail.test_required": (
        "Tests requeridos: {edits} ediciones desde el último test. "
        "Ejecuta tests antes de hacer más cambios."
    ),
    # ── Dispatch Sub-agent ──────────────────────────────────────────────
    "dispatch.description": (
        "Delega una sub-tarea a un agente especializado con su propio contexto "
        "independiente. Útil para investigar, explorar código o ejecutar tests "
        "sin contaminar tu contexto principal. El sub-agente retornará un "
        "resumen de su trabajo.\n\n"
        "Tipos disponibles:\n"
        "- explore: Solo lectura/búsqueda (leer archivos, buscar código)\n"
        "- test: Lectura + ejecución de tests (pytest, etc.)\n"
        "- review: Lectura + análisis de código\n\n"
        "El sub-agente tiene un máximo de 15 pasos y retorna un resumen "
        "de máximo 1000 caracteres."
    ),
    "dispatch.task_description": (
        "Descripción de la sub-tarea a ejecutar. Sé específico sobre qué "
        "quieres que el sub-agente investigue, pruebe o revise."
    ),
    "dispatch.type_description": (
        "Tipo de sub-agente: "
        "'explore' (solo lectura/búsqueda, para investigar), "
        "'test' (lectura + ejecución de tests), "
        "'review' (lectura + análisis de código)"
    ),
    "dispatch.files_description": (
        "Archivos que el sub-agente debería leer para contexto. "
        "Ejemplo: ['src/main.py', 'tests/test_main.py']"
    ),
    "dispatch.invalid_type": (
        "Tipo de sub-agente inválido: '{agent_type}'. "
        "Tipos válidos: {valid_types}"
    ),
    "dispatch.no_result": "Sin resultado del sub-agente.",
    "dispatch.summary_truncated": "\n... (resumen truncado)",
    "dispatch.error": "Error ejecutando sub-agente: {error}",
    "dispatch.subtask_header": "## Sub-tarea ({agent_type})\n\n{task}",
    "dispatch.relevant_files_header": (
        "\n## Archivos Relevantes\n\n"
        "Lee estos archivos para contexto:\n{file_list}"
    ),
    "dispatch.instructions_explore": (
        "\n## Instrucciones\n\n"
        "Investiga y responde la pregunta usando las herramientas de "
        "lectura y búsqueda disponibles. NO modifiques ningún archivo. "
        "Responde con un resumen conciso y útil."
    ),
    "dispatch.instructions_test": (
        "\n## Instrucciones\n\n"
        "Ejecuta los tests relevantes y reporta los resultados. "
        "NO modifiques código. Solo lee archivos y ejecuta tests. "
        "Responde con un resumen de qué tests pasaron/fallaron."
    ),
    "dispatch.instructions_review": (
        "\n## Instrucciones\n\n"
        "Revisa el código de los archivos relevantes. Busca bugs, "
        "problemas de diseño y oportunidades de mejora. "
        "NO modifiques ningún archivo. Responde con un resumen "
        "de tus hallazgos."
    ),
    # ── Ralph Loop ──────────────────────────────────────────────────────
    "ralph.spec_header": "## Especificación de la Tarea\n\n{spec}",
    "ralph.task_header": "## Tarea\n\n{task}",
    "ralph.iteration_instructions": (
        "## Instrucciones de Iteración\n\n"
        "Esta es la **iteración {iteration}/{max_iterations}** "
        "de un loop de corrección automática.\n\n"
        "Cuando hayas completado TODA la tarea y estés seguro de que "
        "todo funciona correctamente, incluye la palabra "
        "`{completion_tag}` en tu respuesta final.\n\n"
        "**Verificaciones que debe pasar tu código:**\n{checks_list}"
    ),
    "ralph.previous_diff": (
        "\n## Cambios de Iteraciones Anteriores\n\n"
        "```diff\n{diff}\n```"
    ),
    "ralph.previous_errors_header": "\n## Errores de la Iteración Anterior\n",
    "ralph.execution_error_header": "\n## Error de Ejecución\n\n```\n{error}\n```",
    "ralph.accumulated_progress": "\n## Progreso Acumulado\n\n{content}",
    "ralph.progress_title": "# Ralph Loop — Progreso\n\n",
    "ralph.progress_auto": "> Auto-generado. No editar manualmente.\n\n",
    "ralph.progress_iteration": "### Iteración {iteration}\n",
    "ralph.progress_status": "- Estado: {status}\n",
    "ralph.progress_steps": "- Pasos: {steps}\n",
    "ralph.progress_cost": "- Coste: ${cost:.4f}\n",
    "ralph.progress_duration": "- Duración: {duration:.1f}s\n",
    "ralph.progress_error": "- Error: {error}\n",
    "ralph.diff_truncated": "\n... (diff truncado)",
    # ── Reviewer ────────────────────────────────────────────────────────
    "reviewer.no_changes": "Sin cambios para revisar.",
    "reviewer.diff_truncated": "\n... (diff truncado)",
    "reviewer.prompt": (
        "## Tarea Original\n{task}\n\n"
        "## Cambios a Revisar\n```diff\n{diff}\n```\n\n"
        "Revisa estos cambios. Lista cada issue encontrado con formato:\n"
        "- **[archivo:linea]** Descripción del problema. Sugerencia de fix.\n\n"
        "Si no hay issues, responde exactamente: 'Sin issues encontrados.'"
    ),
    "reviewer.error": "Error en auto-review: {error}",
    "reviewer.fix_prompt": (
        "Un reviewer encontró estos problemas en tu código:\n\n"
        "{review_text}\n\n"
        "Corrige estos problemas. Asegúrate de que cada issue "
        "mencionado sea resuelto."
    ),
    # ── Reports: Health Delta ───────────────────────────────────────────
    "health.title": "## Code Health Delta\n",
    "health.radon_notice": (
        "> *radon no disponible — complejidad ciclomática no medida. "
        "Instala con `pip install radon`.*\n"
    ),
    "health.col_metric": "Métrica",
    "health.col_before": "Antes",
    "health.col_after": "Después",
    "health.col_delta": "Delta",
    "health.avg_complexity": "Complejidad promedio",
    "health.max_complexity": "Complejidad máxima",
    "health.avg_lines": "Líneas/función (promedio)",
    "health.long_functions": "Funciones largas (>50 líneas)",
    "health.complex_functions": "Funciones complejas (>10)",
    "health.duplicate_blocks": "Bloques duplicados",
    "health.files_analyzed": "**Archivos analizados**: {count}",
    "health.functions_summary": (
        "**Funciones**: {total} "
        "(+{new} nuevas, -{removed} eliminadas)"
    ),
    # ── Reports: Competitive Eval ───────────────────────────────────────
    "competitive.report_title": "# Competitive Eval Report\n",
    "competitive.task_label": "**Tarea**: {task}\n",
    "competitive.models_label": "**Modelos**: {count}\n",
    "competitive.checks_label": "**Checks**: {checks}\n",
    "competitive.results_header": "\n## Resultados\n",
    "competitive.col_model": "Modelo",
    "competitive.col_status": "Estado",
    "competitive.col_steps": "Pasos",
    "competitive.col_cost": "Coste",
    "competitive.col_time": "Tiempo",
    "competitive.col_checks": "Checks",
    "competitive.col_files": "Archivos",
    "competitive.ranking_header": "\n## Ranking\n",
    "competitive.check_details_header": "\n## Detalle de Checks\n",
    "competitive.no_checks_run": "No se ejecutaron checks.\n",
    "competitive.worktrees_header": "\n## Worktrees\n",
    "competitive.worktrees_desc": "Para inspeccionar los resultados de cada modelo:\n",
    # ── Reports: Dryrun ─────────────────────────────────────────────────
    "dryrun.plan_label": "Plan",
    "dryrun.tool_label": "Herramienta",
    "dryrun.args_label": "Argumentos",
    # ── Pipelines ───────────────────────────────────────────────────────
    "pipeline.validation_error": (
        "Pipeline '{path}' tiene errores de validación:\n{errors}"
    ),
    "pipeline.missing_prompt": "falta 'prompt' o está vacío",
    "pipeline.missing_prompt_hint": (
        "falta 'prompt' (el campo 'task' no es válido, usa 'prompt')"
    ),
    "pipeline.unknown_field": "campo desconocido '{field}'",
    "pipeline.unknown_field_hint": (
        "campo desconocido '{field}' (¿quisiste decir 'prompt'?)"
    ),
    "pipeline.invalid_step": "step debe ser un dict/objeto, no {type}",
    "pipeline.no_steps": "el pipeline debe tener al menos un step",
}

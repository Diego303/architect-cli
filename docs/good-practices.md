# Buenas Prácticas — Architect CLI

Guía de buenas prácticas para sacar el máximo partido a `architect`, evitar errores comunes y optimizar costes.

---

## Índice

- [Escribir buenos prompts](#escribir-buenos-prompts)
- [Elegir el agente correcto](#elegir-el-agente-correcto)
- [Edición de archivos](#edición-de-archivos)
- [Ejecución de comandos](#ejecución-de-comandos)
- [Gestión del contexto](#gestión-del-contexto)
- [Optimización de costes](#optimización-de-costes)
- [Hooks del lifecycle](#hooks-del-lifecycle)
- [Guardrails](#guardrails)
- [Skills y contexto del proyecto](#skills-y-contexto-del-proyecto)
- [Memoria procedural](#memoria-procedural)
- [Auto-evaluación](#auto-evaluación)
- [Modos de confirmación](#modos-de-confirmación)
- [Configuración del workspace](#configuración-del-workspace)
- [Uso en CI/CD](#uso-en-cicd)
- [Errores comunes y cómo evitarlos](#errores-comunes-y-cómo-evitarlos)

---

## Escribir buenos prompts

El agente sigue un ciclo interno: **ANALIZAR → PLANIFICAR → EJECUTAR → VERIFICAR → CORREGIR**. Un buen prompt guía cada fase de ese ciclo.

### Sé específico sobre el qué y el dónde

```bash
# Malo — vago, obliga al agente a adivinar
architect run "arregla el bug del login"

# Bueno — indica archivo, síntoma y pista
architect run "el endpoint POST /login retorna 401 con credenciales válidas. \
  El problema está probablemente en src/auth.py en la función validate_token(). \
  Verifica la comprobación de expiración del JWT."
```

Un prompt específico ahorra entre 5 y 10 pasos de exploración. Cada paso cuesta tokens y consume contexto.

### Describe el resultado esperado

```bash
# Malo — no dice qué quiere como resultado
architect run "mejora el módulo de users"

# Bueno — describe el estado final deseado
architect run "en src/models/user.py, cambia la clase User de dataclass \
  a Pydantic BaseModel. Mantén los valores por defecto. Añade \
  model_config = {'extra': 'forbid'}. Actualiza los imports en \
  los archivos que usan User."
```

### Un objetivo por ejecución

El agente funciona mejor con tareas focalizadas. En lugar de un prompt largo con 5 tareas, ejecuta 5 veces con prompts cortos.

```bash
# Peor — demasiados objetivos en un solo prompt
architect run "refactoriza utils.py, añade tests, actualiza docs, \
  corrige el bug de parseo y migra a async"

# Mejor — una tarea por ejecución
architect run "migra las funciones de utils.py a Pydantic v2" --mode yolo
architect run "genera tests para los nuevos modelos Pydantic" --mode yolo
architect run "actualiza docs/models.md con los nuevos schemas" --mode yolo
```

### Menciona el contexto que el agente no puede deducir

El agente ve el árbol del proyecto y puede leer archivos, pero no sabe cosas como:

- Convenciones del equipo que no están documentadas en el código.
- Por qué se eligió un patrón sobre otro.
- Requisitos de negocio que no se reflejan en el código.

```bash
# Incluir contexto no visible en el código
architect run "añade validación de NIF español al campo tax_id de User. \
  Usamos la librería stdnum para validaciones fiscales (ya está en requirements). \
  El formato esperado es con letra al final, sin guiones."
```

---

## Elegir el agente correcto

| Tarea | Agente | Por qué |
|-------|--------|---------|
| Implementar código | `build` (default) | Tiene todas las tools: lectura, escritura, búsqueda, comandos |
| Entender código | `resume` | Rápido, barato, 15 pasos máximo |
| Planificar antes de implementar | `plan` | Solo lectura, produce un plan sin tocar nada |
| Code review | `review` | Focalizado en feedback, no modifica archivos |
| Tarea sensible (producción) | `build` con `confirm-all` | Confirma cada operación |
| Automatización CI | `build` o `review` con `yolo` | Sin confirmaciones interactivas |

**Patrón recomendado para tareas grandes:**

```bash
# 1. Planificar (barato, solo lectura)
architect run "¿cómo añadir autenticación JWT?" -a plan --json > plan.json

# 2. Revisar el plan
cat plan.json | jq -r '.output'

# 3. Implementar con el plan como referencia
PLAN=$(jq -r '.output' plan.json)
architect run "Implementa este plan: ${PLAN}" --mode yolo --self-eval basic
```

---

## Edición de archivos

### Jerarquía de edición

| Situación | Herramienta | Motivo |
|-----------|-------------|--------|
| Cambiar un bloque contiguo | `edit_file` | Preciso, genera diff, preferido |
| Cambios en múltiples secciones | `apply_patch` | Un solo paso para multi-hunk |
| Archivo nuevo o reescritura completa | `write_file` | Crea desde cero |

### Regla de unicidad de edit_file

`edit_file` requiere que el `old_str` sea **único** en el archivo. Si aparece 0 o 2+ veces, falla.

**Cómo evitar problemas:**

El agente normalmente maneja esto bien. Pero si ves errores de "old_str aparece N veces", puedes ayudar en el prompt:

```bash
# Mencionar contexto para que el agente incluya líneas de alrededor
architect run "en config.py, cambia el timeout de la función connect() \
  (no el timeout de la función retry()) de 30 a 60 segundos"
```

### Prefer edit_file sobre write_file para cambios

`write_file` sobreescribe todo el contenido. Si el agente lee un archivo de 500 líneas y lo reescribe para cambiar 2, puede perder formateo o introducir errores. `edit_file` solo toca el bloque exacto.

---

## Ejecución de comandos

### Habilitar cuando lo necesites

Por defecto, `run_command` está habilitado pero el agente `build` requiere confirmación para comandos "dev" (pytest, mypy, ruff). Con `--mode yolo` se ejecutan sin preguntar.

```bash
# Que el agente pueda ejecutar tests sin confirmar
architect run "corrige el bug y ejecuta pytest para verificar" \
  --mode yolo --allow-commands
```

### Comandos seguros, dev y peligrosos

El sistema clasifica cada comando automáticamente:

| Categoría | Ejemplos | Confirmación en `confirm-sensitive` |
|-----------|----------|-------------------------------------|
| **safe** | `ls`, `cat`, `git status`, `git log`, `python --version` | Auto-aprobado |
| **dev** | `pytest`, `mypy`, `ruff`, `npm test`, `cargo test`, `make` | Auto-aprobado |
| **dangerous** | Scripts custom, comandos desconocidos | Requiere confirmación |

Si usas herramientas no estándar, añádelas a la config:

```yaml
commands:
  safe_commands:
    - "my-linter --check"
    - "custom-test-runner"
```

### Timeouts

El timeout por defecto es 30 segundos. Si tus tests o builds tardan más:

```yaml
commands:
  default_timeout: 120   # 2 minutos
```

### Lo que siempre se bloquea

Estos patrones están bloqueados en todas las circunstancias:

- `rm -rf /` — Destrucción del sistema.
- `sudo` — Escalación de privilegios.
- `curl | bash`, `wget | sh` — Ejecución remota de código.
- `dd of=/dev/` — Escritura directa a disco.
- `chmod 777` — Permisos inseguros.
- `mkfs` — Formateo de disco.
- Fork bombs.

No hay override para estos. Es una decisión de diseño para seguridad.

---

## Gestión del contexto

El agente mantiene un historial de mensajes con el LLM. A medida que se acumulan pasos, el contexto crece y puede saturarse.

### Los tres niveles de protección

1. **Truncado de tool results**: Los resultados de tools mayores a `max_tool_result_tokens` se cortan, manteniendo principio y final del output.
2. **Compresión de pasos antiguos**: Después de N pasos con tool calls, los más antiguos se resumen con el LLM (coste extra: ~500 tokens por compresión).
3. **Ventana deslizante**: Si el contexto supera `max_context_tokens`, se eliminan los mensajes más antiguos.

### Cómo evitar llenar el contexto

- **Busca antes de leer.** Usa `search_code` o `grep` para localizar el código relevante en vez de leer archivos enteros.
- **Una tarea por ejecución.** No pidas 5 refactorizaciones en un solo prompt.
- **Controla el número de pasos.** Si ves que una tarea consume 30+ pasos regularmente, divídela.
- **Ajusta los umbrales** para proyectos grandes:

```yaml
context:
  max_tool_result_tokens: 2000     # Tokens por resultado de tool
  summarize_after_steps: 8         # Comprimir tras 8 pasos con tools
  keep_recent_steps: 4             # Mantener los 4 pasos más recientes
  max_context_tokens: 80000        # Límite hard del contexto total
```

### Cuándo aumentar `max_context_tokens`

Depende del modelo:

| Modelo | Context window real | Valor recomendado |
|--------|--------------------:|------------------:|
| gpt-4o | 128K | 80,000–100,000 |
| gpt-4o-mini | 128K | 80,000–100,000 |
| claude-sonnet-4-6 | 200K | 120,000–160,000 |
| claude-opus-4-6 | 200K | 120,000–160,000 |
| ollama/llama3 (8B) | 8K | 4,000–6,000 |

Deja un 20-30% de margen para el system prompt y el índice del proyecto.

---

## Optimización de costes

### Elegir el modelo según la tarea

| Tarea | Modelo recomendado | Coste relativo |
|-------|--------------------|----------------|
| Review, resumen, planificación | `gpt-4o-mini` | Muy bajo |
| Implementación simple (1-3 archivos) | `gpt-4o` | Medio |
| Refactorización compleja | `claude-sonnet-4-6` | Medio-alto |
| Tareas críticas con auto-eval full | `gpt-4o` / `claude-sonnet-4-6` | Alto |

```bash
# Review barato
architect run "revisa src/auth.py" -a review --model gpt-4o-mini

# Implementación con modelo potente
architect run "refactoriza el ORM completo" --model claude-sonnet-4-6
```

### Activar prompt caching

Reduce el coste del system prompt un 90% en llamadas consecutivas al mismo modelo. El cache dura ~5 minutos.

```yaml
llm:
  prompt_caching: true
```

Es especialmente útil cuando ejecutas varias tareas seguidas sobre el mismo proyecto:

```bash
architect run "paso 1..." --model claude-sonnet-4-6
architect run "paso 2..." --model claude-sonnet-4-6   # 90% más barato en system prompt
architect run "paso 3..." --model claude-sonnet-4-6   # idem
```

### Establecer budget

Siempre usa `--budget` en automatización para evitar costes descontrolados:

```bash
architect run "..." --budget 2.00 --show-costs
```

El agente se detiene con `status: "partial"` y `stop_reason: "budget_exceeded"` si supera el límite. Antes de parar, genera un resumen de lo que hizo.

```yaml
# Config con warning temprano
costs:
  enabled: true
  budget_usd: 5.00
  warn_at_usd: 2.00    # Log warning al llegar a $2
```

### Cache local para desarrollo

Si estás iterando sobre el mismo prompt (debugging, ajuste de config), activa el cache local:

```bash
architect run "..." --cache
# Segunda ejecución con mismo prompt → respuesta instantánea, 0 tokens
```

No usar en producción: las respuestas cacheadas pueden quedar obsoletas si el código cambia.

---

## Hooks del lifecycle

### Cuándo usarlos

Los hooks ejecutan automáticamente linters, formateadores o type checkers. A partir de v0.16.0, se soportan 10 eventos del lifecycle (no solo post-edición).

```yaml
hooks:
  post_tool_use:
    - name: format
      command: "black {file}"
      file_patterns: ["*.py"]
      timeout: 10
    - name: lint
      command: "ruff check {file}"
      file_patterns: ["*.py"]
      timeout: 10
  pre_tool_use:
    - name: validate-secrets
      command: "bash scripts/check-secrets.sh"
      matcher: "write_file|edit_file"
      timeout: 5
```

### Buenas prácticas con hooks

**Mantén los hooks rápidos.** Cada hook añade tiempo y potencialmente una iteración extra si falla. Un hook de 30s en cada edición suma rápido.

**Evita tests en hooks.** Los tests suelen ser lentos. Es mejor que el agente los ejecute explícitamente con `run_command` una vez al final, o usa quality gates de guardrails para verificar al completar.

```yaml
# Bien — hooks rápidos de formateo y lint
hooks:
  post_tool_use:
    - name: format
      command: "black {file}"
      file_patterns: ["*.py"]
      timeout: 10
```

**Usa pre-hooks para seguridad, post-hooks para calidad.** Los pre-hooks con exit code 2 bloquean la acción; los post-hooks informan al LLM.

**Si un hook está roto, desactívalo.** Un linter mal configurado que siempre falla causa que el agente entre en un bucle intentando corregir errores que no son suyos.

```yaml
hooks:
  post_tool_use:
    - name: broken-lint
      command: "..."
      enabled: false     # Desactivado
```

**Usa async para notificaciones.** Los hooks de sesión que envían notificaciones (Slack, email) deben ser async para no bloquear.

```yaml
hooks:
  session_end:
    - name: notify
      command: "curl -s $SLACK_WEBHOOK -d 'Sesión completada'"
      async: true
```

---

## Guardrails

### Cuándo usarlos

Los guardrails son reglas **deterministas** de seguridad que se evalúan ANTES que los hooks. Ideales para equipos o entornos donde se necesita control estricto.

### Buenas prácticas con guardrails

**Protege archivos sensibles.** Siempre añade `.env`, certificados y configuraciones de producción a `protected_files`.

```yaml
guardrails:
  enabled: true
  protected_files:
    - ".env*"
    - "*.pem"
    - "*.key"
    - "deploy/**"
    - "Dockerfile"
```

**Limita el alcance de cambios.** En entornos de CI o con agentes de confianza parcial, limita cuánto puede cambiar el agente.

```yaml
guardrails:
  max_files_modified: 10
  max_lines_changed: 500
```

**Usa quality gates para verificación final.** Son más efectivos que tests en hooks porque se ejecutan una sola vez al completar.

```yaml
guardrails:
  quality_gates:
    - name: tests
      command: "pytest tests/ -x --tb=short"
      required: true
      timeout: 120
    - name: lint
      command: "ruff check src/"
      required: false    # solo informativo
```

**Usa code_rules para patrones prohibidos.** Útil para prevenir anti-patterns en el código generado.

```yaml
guardrails:
  code_rules:
    - pattern: "eval\\("
      message: "No usar eval() — riesgo de inyección"
      severity: block
    - pattern: "console\\.log"
      message: "Usar logger en vez de console.log"
      severity: warn
```

---

## Skills y contexto del proyecto

### Cuándo usarlos

Las skills inyectan contexto del proyecto en el system prompt del agente. Son la forma de comunicar convenciones del equipo, patrones preferidos y reglas del proyecto.

### Buenas prácticas con skills

**Crea un `.architect.md` en cada proyecto.** Es la forma más efectiva de dar contexto al agente sin repetirlo en cada prompt.

```markdown
<!-- .architect.md -->
# Convenciones

- Python: snake_case, black, ruff, mypy
- Tests en tests/ con pytest
- Usar pydantic v2 para validación
- No usar print(), usar structlog
```

**Usa skills con globs para contexto específico.** Si las reglas de Django solo aplican a ciertos archivos, usa globs.

```markdown
---
name: django-patterns
globs: ["**/views.py", "**/models.py", "**/serializers.py"]
---
# Patrones Django
- Usar class-based views
- Validar con serializers, nunca en views
```

**No repitas en skills lo que el código ya dice.** Las skills son para convenciones implícitas, no para documentar lo que ya es visible en el código.

---

## Memoria procedural

### Cuándo usarla

La memoria procedural detecta correcciones del usuario y las persiste para futuras sesiones. Útil para proyectos donde se interactúa repetidamente con el agente.

### Buenas prácticas con memoria

**Actívala en proyectos recurrentes.** Si trabajas con el agente en el mismo proyecto durante días/semanas, la memoria reduce las correcciones repetidas.

```yaml
memory:
  enabled: true
```

**Revisa `.architect/memory.md` periódicamente.** Las correcciones auto-detectadas pueden contener ruido. Edita el archivo manualmente para mantener solo las reglas relevantes.

**Usa patrones para reglas permanentes.** Además de las correcciones automáticas, puedes añadir reglas manualmente:

```markdown
- [2026-02-22] Patron: Siempre usar pnpm, nunca npm ni yarn
- [2026-02-22] Patron: Los tests van en __tests__/ junto al código
```

---

## Auto-evaluación

### Cuándo usar cada modo

| Modo | Coste extra | Cuándo usarlo |
|------|-------------|---------------|
| `off` | 0 | Tareas triviales, exploración, desarrollo rápido |
| `basic` | ~500 tokens | Quality gate en CI, verificación post-implementación |
| `full` | 2-5x del coste base | Tareas críticas que deben estar correctas |

```bash
# CI — verificar que la tarea se completó
architect run "..." --self-eval basic

# Tarea crítica — re-ejecutar si falla la evaluación
architect run "..." --self-eval full

# Desarrollo rápido — sin evaluación extra
architect run "..." --self-eval off
```

### Cuidado con `full` mode

El modo `full` puede re-ejecutar el agente hasta `max_retries` veces (default: 2). Esto significa que el coste puede multiplicarse por 3-5x:

```
Ejecución base:    1000 tokens    $0.02
Evaluación 1:       500 tokens    $0.01  → "incompleto"
Re-ejecución 1:     800 tokens    $0.015
Evaluación 2:       500 tokens    $0.01  → "completado"
─────────────────────────────────────────
Total:             2800 tokens    $0.055 (2.75x del coste base)
```

Usa `--budget` junto con `--self-eval full` para limitar el gasto:

```bash
architect run "..." --self-eval full --budget 1.00
```

### Umbral de confianza

El evaluador retorna una confianza entre 0 y 1. Si es menor que `confidence_threshold` (default: 0.8), se considera incompleto.

```yaml
evaluation:
  mode: full
  max_retries: 2
  confidence_threshold: 0.8   # 80% mínimo para aceptar
```

Baja el umbral si tus tareas son inherentemente ambiguas (documentación, refactorizaciones grandes):

```yaml
evaluation:
  confidence_threshold: 0.6   # Más permisivo
```

---

## Modos de confirmación

### Cuándo usar cada modo

| Modo | Uso ideal | Riesgo |
|------|-----------|--------|
| `confirm-sensitive` | Desarrollo diario | Bajo: solo confirmas escrituras |
| `confirm-all` | Operaciones en producción | Nulo: confirmas todo |
| `yolo` | CI/CD, automatización, tareas de confianza | Medio: el agente actúa sin preguntar |

### confirm-sensitive (default del build agent)

Es el balance recomendado para desarrollo diario:
- Lecturas y búsquedas se ejecutan automáticamente.
- Escrituras de archivos piden confirmación.
- Comandos safe/dev se ejecutan automáticamente.
- Comandos desconocidos piden confirmación.

### yolo — imprescindible en CI

En entornos sin terminal (CI/CD, contenedores, cron), `confirm-sensitive` y `confirm-all` bloquean la ejecución porque no hay terminal para responder. Siempre usa `--mode yolo`:

```bash
# CI headless
architect run "..." --mode yolo --budget 2.00
```

### Combinación segura para yolo

Si usas `yolo` pero quieres limitar el riesgo:

```yaml
workspace:
  allow_delete: false          # Prohibir borrado de archivos

commands:
  allowed_only: true           # Solo comandos safe + dev
  blocked_patterns:
    - "git push"               # Prohibir push desde el agente
    - "docker rm"              # Prohibir borrado de contenedores

costs:
  budget_usd: 2.00             # Límite de gasto
```

---

## Configuración del workspace

### Prevención de path traversal

Architect confina todas las operaciones de archivos al workspace root. El agente no puede leer ni escribir fuera de este directorio, ni con paths relativos (`../../etc/passwd`) ni con symlinks.

```bash
# El workspace es el directorio actual por defecto
architect run "..." -w /home/user/mi-proyecto
```

### Excluir directorios del indexador

Si tu proyecto tiene directorios pesados que no necesitan indexarse:

```yaml
indexer:
  exclude_dirs:
    - vendor
    - .terraform
    - coverage
    - data
  exclude_patterns:
    - "*.generated.go"
    - "*.pb.go"
```

Esto acelera el startup y reduce el tamaño del system prompt.

### Proyectos grandes

Para repos con más de 300 archivos, el indexador genera un árbol compacto agrupado por directorio. Si el indexador tarda mucho, desactiva el cache en disco durante desarrollo:

```yaml
indexer:
  use_cache: true   # Cache en disco, TTL 5 minutos
```

---

## Uso en CI/CD

### Checklist para CI

1. Usar `--mode yolo` (sin terminal interactivo).
2. Usar `--quiet --json` (salida parseable).
3. Establecer `--budget` (control de costes).
4. Verificar exit code (0=ok, 1=fallo, 2=parcial).
5. API key como secret del CI, nunca en código.

```bash
architect run "..." \
  --mode yolo \
  --quiet --json \
  --budget 1.00 \
  > result.json

EXIT_CODE=$?
STATUS=$(jq -r '.status' result.json)

if [ "$EXIT_CODE" -ne 0 ] || [ "$STATUS" != "success" ]; then
  echo "Architect falló: status=${STATUS}, exit=${EXIT_CODE}"
  jq -r '.output // empty' result.json
  exit 1
fi
```

### Config recomendada para CI

```yaml
llm:
  model: gpt-4o-mini
  stream: false
  prompt_caching: true

commands:
  enabled: true
  allowed_only: true

evaluation:
  mode: basic

costs:
  enabled: true
  budget_usd: 1.00
```

---

## Errores comunes y cómo evitarlos

### 1. El agente se queda colgado esperando confirmación

**Causa:** Modo `confirm-sensitive` o `confirm-all` en un entorno sin terminal.

**Solución:** Usar `--mode yolo`.

### 2. edit_file falla con "old_str aparece N veces"

**Causa:** El texto a reemplazar no es único en el archivo.

**Solución:** El agente normalmente reintenta con más contexto. Si persiste, el prompt puede ayudar indicando la función o sección exacta donde hacer el cambio.

### 3. Coste inesperadamente alto

**Causa:** Tarea compleja + `--self-eval full` + muchas iteraciones de hooks.

**Solución:**
- Usar `--budget` siempre.
- Usar `--self-eval basic` en vez de `full`.
- Elegir modelo más barato para tareas simples.
- Activar `prompt_caching: true`.

### 4. El agente no encuentra archivos que existen

**Causa:** El archivo está en un directorio excluido por el indexador (node_modules, .venv, etc.).

**Solución:** Ajustar `indexer.exclude_dirs` en la config o indicar el path exacto en el prompt.

### 5. run_command falla con "comando bloqueado"

**Causa:** El comando coincide con un patrón de la blocklist.

**Solución:** Los comandos de la blocklist están bloqueados por seguridad y no se pueden desbloquear. Si el comando es legítimo pero similar (por ejemplo, `rm -rf ./build/` se confunde con `rm -rf /`), el agente normalmente reintenta con una alternativa segura.

### 6. Timeout del agente

**Causa:** La tarea es demasiado grande para el timeout configurado.

**Solución:** Aumentar `--timeout` o dividir la tarea en subtareas.

```bash
architect run "..." --timeout 600   # 10 minutos
```

### 7. "Budget exceeded" con status partial

**Causa:** El coste acumulado superó el budget antes de completar la tarea.

**Solución:** El agente genera un resumen de lo que hizo antes de parar. Puedes continuar desde donde lo dejó:

```bash
# Primera ejecución (se queda en partial)
architect run "refactoriza todo el módulo auth" --budget 1.00 --json > result1.json

# Continuar si quedó parcial
STATUS=$(jq -r '.status' result1.json)
if [ "$STATUS" = "partial" ]; then
  OUTPUT=$(jq -r '.output' result1.json)
  architect run "Continúa esta tarea. Progreso anterior: ${OUTPUT}" \
    --budget 1.00
fi
```

### 8. El indexador tarda mucho en repos grandes

**Causa:** Repo con miles de archivos o archivos muy grandes.

**Solución:**

```yaml
indexer:
  max_file_size: 500000       # 500KB en vez de 1MB
  exclude_dirs:
    - data
    - vendor
    - assets
  use_cache: true              # Cache 5 min en disco
```

---

## Resumen rápido

| Práctica | Recomendación |
|----------|---------------|
| Prompts | Específicos, un objetivo por ejecución |
| Agente | `review`/`plan` para análisis, `build` para cambios |
| Edición | Preferir `edit_file` sobre `write_file` |
| Comandos | Hooks rápidos, tests solo con `run_command` o quality gates |
| Contexto | Buscar antes de leer, dividir tareas grandes |
| Costes | `prompt_caching: true`, `--budget`, modelo adecuado |
| Hooks | Pre-hooks para seguridad, post-hooks para lint/format, async para notificaciones |
| Guardrails | Proteger archivos sensibles, limitar alcance, quality gates al final |
| Skills | `.architect.md` en cada proyecto, skills con globs para contexto específico |
| Memoria | Activar en proyectos recurrentes, revisar `.architect/memory.md` periódicamente |
| Evaluación | `basic` para CI, `full` solo para tareas críticas |
| Modo | `confirm-sensitive` en local, `yolo` en CI |
| Seguridad | `allowed_only: true`, `allow_delete: false`, guardrails en CI |

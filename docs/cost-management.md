# Gestion de Costes en Architect CLI

## Introduccion

Las llamadas a modelos de lenguaje (LLM) tienen un coste directo medido en tokens consumidos. En flujos de trabajo donde un agente autonomo ejecuta decenas de pasos, cada paso con miles de tokens de contexto, el gasto puede escalar rapidamente si no se monitoriza y controla.

Architect CLI incluye un sistema completo de gestion de costes que cubre tres necesidades:

1. **Tracking**: registrar el coste exacto de cada llamada al LLM, desglosado por modelo, tokens y fuente.
2. **Presupuesto**: establecer limites de gasto por ejecucion con cierre graceful cuando se exceden.
3. **Optimizacion**: reducir costes mediante prompt caching, seleccion de modelo y cache local de desarrollo.

Este documento explica como funciona cada componente, como configurarlo y como aplicar estrategias de optimizacion para mantener los costes bajo control.

---

## Como funciona el tracking de costes

### CostTracker: registro por paso

El nucleo del sistema es `CostTracker` (en `src/architect/costs/tracker.py`). Cada vez que el agente hace una llamada al LLM, el tracker registra un `StepCost` con la siguiente informacion:

- **step**: numero de paso del agente
- **model**: modelo utilizado (e.g., `gpt-4o`, `claude-sonnet-4-6`)
- **input_tokens**: tokens de entrada (prompt completo)
- **output_tokens**: tokens de salida (respuesta del modelo)
- **cached_tokens**: tokens servidos desde la cache del proveedor (coste reducido)
- **cost_usd**: coste calculado en dolares
- **source**: origen de la llamada: `"agent"` (loop principal), `"eval"` (self-evaluation) o `"summary"` (compresion de contexto)

```python
# Ejemplo interno: asi registra el agente cada llamada
cost_tracker.record(
    step=5,
    model="gpt-4o",
    usage={"prompt_tokens": 8500, "completion_tokens": 1200, "cache_read_input_tokens": 3000},
    source="agent",
)
```

### PriceLoader: resolucion de precios

`PriceLoader` (en `src/architect/costs/prices.py`) resuelve el precio de cada modelo siguiendo un orden de prioridad:

1. **Match exacto**: el nombre del modelo coincide con una clave en la tabla de precios.
2. **Match por prefijo**: el modelo empieza con una clave registrada (e.g., `gpt-4o-2024-08-06` matchea con `gpt-4o`).
3. **Match por nombre base**: se extrae el prefijo base y se busca coincidencia.
4. **Fallback generico**: si no se encuentra ninguna coincidencia, se aplican precios conservadores de $3.00 / $15.00 por millon de tokens (input/output).

Los precios se cargan desde `src/architect/costs/default_prices.json` al iniciar. Opcionalmente, se pueden sobreescribir con un archivo custom via configuracion.

### Conteo de tokens: input, output y cached

El coste de una llamada se calcula con esta formula:

```
coste = (tokens_no_cacheados / 1M) * precio_input
      + (tokens_cacheados / 1M)    * precio_cached_input
      + (tokens_output / 1M)       * precio_output
```

Donde `tokens_no_cacheados = input_tokens - cached_tokens`.

Si el modelo no tiene precio de cached input definido, los tokens cacheados se cobran al precio normal de input.

### BudgetExceededError: cierre graceful

Cuando el coste acumulado supera el presupuesto configurado (`budget_usd`), el tracker lanza `BudgetExceededError`. El loop del agente captura esta excepcion y realiza un cierre graceful:

- Se detiene la ejecucion del agente.
- Se retorna el resultado parcial con `status: "partial"`.
- Se incluye el resumen de costes en la salida.

Adicionalmente, existe un umbral de aviso (`warn_at_usd`) que emite un log warning cuando se alcanza, sin detener la ejecucion. Esto permite configurar alertas antes de que se agote el presupuesto completo.

---

## Tabla de precios por modelo

Precios actualizados a febrero 2026. Todos los valores son en USD por millon de tokens.

| Modelo | Input $/1M | Output $/1M | Cached Input $/1M |
|---|---:|---:|---:|
| **OpenAI** | | | |
| `gpt-4o` | 2.50 | 10.00 | 1.25 |
| `gpt-4o-mini` | 0.15 | 0.60 | 0.075 |
| `gpt-4.1` | 2.00 | 8.00 | 0.50 |
| `gpt-4.1-mini` | 0.40 | 1.60 | 0.10 |
| `gpt-4.1-nano` | 0.10 | 0.40 | 0.025 |
| `o1` | 15.00 | 60.00 | 7.50 |
| `o1-mini` | 1.10 | 4.40 | 0.55 |
| `o3-mini` | 1.10 | 4.40 | 0.55 |
| **Anthropic** | | | |
| `claude-opus-4-6` | 15.00 | 75.00 | 1.50 |
| `claude-sonnet-4-6` | 3.00 | 15.00 | 0.30 |
| `claude-haiku-4-5` | 0.80 | 4.00 | 0.08 |
| `claude-opus-4` | 15.00 | 75.00 | 1.50 |
| `claude-sonnet-4` | 3.00 | 15.00 | 0.30 |
| `claude-haiku-4` | 0.80 | 4.00 | 0.08 |
| `claude-3-5-sonnet` | 3.00 | 15.00 | 0.30 |
| `claude-3-5-haiku` | 0.80 | 4.00 | 0.08 |
| **Google** | | | |
| `gemini/gemini-2.0-flash` | 0.10 | 0.40 | 0.025 |
| `gemini/gemini-2.5-pro` | 1.25 | 10.00 | 0.315 |
| `gemini/gemini-1.5-pro` | 1.25 | 5.00 | 0.3125 |
| **DeepSeek** | | | |
| `deepseek/deepseek-chat` | 0.27 | 1.10 | 0.07 |
| `deepseek/deepseek-reasoner` | 0.55 | 2.19 | 0.14 |
| **Otros** | | | |
| `ollama` (local) | 0.00 | 0.00 | 0.00 |
| `together_ai` | 0.90 | 0.90 | -- |
| *(fallback generico)* | 3.00 | 15.00 | -- |

### Guia de seleccion de modelo por tipo de tarea

| Tarea | Modelo recomendado | Razon |
|---|---|---|
| Code review, linting | `gpt-4o-mini`, `claude-haiku-4-5`, `gemini-2.0-flash` | Tareas simples que no requieren razonamiento profundo |
| Planificacion, diseno | `gpt-4o`, `claude-sonnet-4-6`, `gemini-2.5-pro` | Buen equilibrio entre calidad y coste |
| Refactoring complejo | `gpt-4.1`, `claude-sonnet-4-6` | Alta calidad de codigo a coste moderado |
| Arquitectura critica | `claude-opus-4-6`, `o1` | Maxima capacidad de razonamiento |
| Desarrollo iterativo | `ollama` (local) | Coste cero, ideal para experimentar |
| Tareas de bajo coste | `gpt-4.1-nano`, `deepseek/deepseek-chat` | Ultra bajo coste para tareas sencillas |

---

## Configuracion de costes

### Configuracion YAML

En el archivo `architect.yaml` del proyecto:

```yaml
costs:
  enabled: true               # Activar/desactivar tracking de costes (default: true)
  budget_usd: 1.00            # Limite de gasto en USD por ejecucion (null = sin limite)
  warn_at_usd: 0.75           # Umbral de aviso (log warning al alcanzarlo)
  prices_file: ./my_prices.json  # Archivo JSON con precios custom (opcional)
```

**`costs.enabled`**: cuando es `true` (por defecto), se registra el coste de cada llamada al LLM. Si se desactiva, no se calcula ningun coste ni se aplica presupuesto.

**`costs.budget_usd`**: limite maximo de gasto en dolares por ejecucion. Si el coste acumulado lo supera, el agente se detiene con `status: "partial"`. Establecerlo a `null` (por defecto) desactiva el limite.

**`costs.warn_at_usd`**: umbral de aviso. Cuando el gasto acumulado alcanza este valor, se emite un log warning. No detiene la ejecucion. Util para anticipar que el presupuesto se esta agotando.

**`costs.prices_file`**: ruta a un archivo JSON con precios custom. Tiene el mismo formato que `default_prices.json`. Los precios custom sobreescriben los defaults para los modelos especificados.

### Flags de CLI

```bash
# Establecer presupuesto desde la linea de comandos
architect run "refactoriza el modulo auth" --budget 0.50

# Mostrar resumen de costes al terminar
architect run "genera tests" --show-costs

# Combinar presupuesto y visualizacion de costes
architect run "refactoriza todo" --budget 0.50 --show-costs
```

| Flag | Descripcion |
|---|---|
| `--budget FLOAT` | Limite de gasto en USD para esta ejecucion |
| `--show-costs` | Mostrar resumen de costes al finalizar |

El flag `--budget` sobreescribe el valor de `costs.budget_usd` del archivo YAML para esa ejecucion.

### Variables de entorno

Architect soporta las siguientes variables de entorno relevantes para costes:

| Variable | Efecto |
|---|---|
| `ARCHITECT_MODEL` | Sobreescribe el modelo por defecto (`llm.model`) |
| `ARCHITECT_API_BASE` | Sobreescribe la URL base de la API (`llm.api_base`) |

Para usar un modelo local via Ollama:

```bash
export ARCHITECT_MODEL=ollama/llama3
export ARCHITECT_API_BASE=http://localhost:11434
architect run "tu tarea" --show-costs
# Coste: $0.0000
```

---

## Prompt caching -- reducir costes hasta un 90%

### Como funciona

El prompt caching es una funcionalidad de los proveedores de LLM (principalmente Anthropic) que permite cachear el system prompt entre llamadas consecutivas. En un flujo tipico del agente, el system prompt es identico en todos los pasos; solo cambian los mensajes del historial.

Cuando prompt caching esta activo, Architect anade `cache_control` al system message. El proveedor cachea ese contenido y en las llamadas posteriores lo sirve desde cache a un precio significativamente reducido.

**Ahorro tipico**: los modelos de Anthropic cobran el cached input al 10% del precio normal. Esto significa que un system prompt de 5,000 tokens que se reutiliza 20 veces cuesta ~90% menos que sin caching.

### Proveedores soportados

| Proveedor | Soporte | Ratio de ahorro |
|---|---|---|
| Anthropic (Claude) | Completo | ~90% en tokens cacheados |
| OpenAI (GPT-4o) | Completo | ~50% en tokens cacheados |
| Google (Gemini) | Completo | ~75% en tokens cacheados |
| DeepSeek | Completo | ~74% en tokens cacheados |
| Ollama (local) | N/A | Coste $0 siempre |

### Configuracion

```yaml
llm:
  model: claude-sonnet-4-6
  prompt_caching: true   # Activar prompt caching (default: false)
```

### Cuando usarlo

- **Recomendado**: proyectos donde se ejecuta Architect repetidamente con el mismo system prompt (desarrollo iterativo, CI/CD).
- **Especialmente util**: con modelos Anthropic donde el ahorro es del ~90%.
- **Impacto**: mayor en ejecuciones largas (muchos steps) donde el system prompt se repite en cada llamada.
- **Sin efecto**: con modelos locales (Ollama) donde el coste ya es $0.

**Ejemplo de ahorro**: con `claude-sonnet-4-6` y un system prompt de 4,000 tokens en una ejecucion de 15 steps:

- Sin caching: 15 * 4,000 = 60,000 tokens a $3.00/M = $0.18
- Con caching: 4,000 a $3.00/M + 14 * 4,000 a $0.30/M = $0.012 + $0.0168 = $0.029
- **Ahorro: ~84%** en coste de system prompt

---

## Cache local de respuestas LLM

### Que es

`LocalLLMCache` (en `src/architect/llm/cache.py`) es un cache determinista en disco que almacena respuestas completas del LLM. Cuando los mensajes y tools de una llamada son identicos a una llamada previa, se devuelve la respuesta cacheada sin hacer ninguna llamada a la API.

**Importante**: este cache es exclusivamente para desarrollo. No debe usarse en produccion porque las respuestas cacheadas no reflejan cambios en el contexto del proyecto.

### Como funciona

1. Se genera una clave SHA-256 del JSON canonico de `(messages, tools)`.
2. Se busca un archivo `{hash}.json` en el directorio de cache.
3. Si existe y no ha expirado (TTL), se devuelve la respuesta almacenada.
4. Si no existe o ha expirado, se hace la llamada al LLM y se guarda la respuesta.

Los fallos del cache son silenciosos: nunca rompen el flujo del agente.

### Configuracion YAML

```yaml
llm_cache:
  enabled: false              # Activar cache local (default: false)
  dir: ~/.architect/cache     # Directorio de almacenamiento
  ttl_hours: 24               # Horas de validez de cada entrada (1-8760)
```

### Flags de CLI

```bash
# Activar cache local para esta ejecucion
architect run "genera tests" --cache

# Desactivar cache aunque este habilitado en YAML
architect run "genera tests" --no-cache

# Limpiar toda la cache antes de ejecutar
architect run "genera tests" --cache-clear
```

| Flag | Descripcion |
|---|---|
| `--cache` | Activar cache local de LLM para esta ejecucion |
| `--no-cache` | Desactivar cache local aunque este habilitado en config |
| `--cache-clear` | Eliminar todas las entradas de cache antes de ejecutar |

### Cuando usarlo

- **Desarrollo iterativo**: cuando se prueba el mismo prompt repetidamente y se quiere evitar pagar por cada prueba.
- **Depuracion**: para reproducir comportamientos exactos del agente.
- **No en produccion**: las respuestas cacheadas no tienen en cuenta cambios en archivos del proyecto.
- **No con prompts dinamicos**: si el prompt cambia en cada ejecucion, el cache tendra hits rate muy bajo.

---

## Estimaciones de coste por tipo de tarea

Las estimaciones asumen el uso de `gpt-4o` como modelo principal. Los costes reales varian segun la complejidad del proyecto, el tamano de los archivos y la calidad del prompt.

| Tipo de tarea | Steps tipicos | Coste estimado | Modelo recomendado | Budget sugerido |
|---|:---:|---:|---|---:|
| Code review simple | 3-5 | $0.01 - $0.05 | `gpt-4o-mini` | $0.10 |
| Planificacion | 3-5 | $0.03 - $0.10 | `gpt-4o` | $0.20 |
| Cambio de codigo pequeno | 5-10 | $0.05 - $0.20 | `gpt-4o` | $0.50 |
| Generacion de tests | 8-15 | $0.10 - $0.40 | `gpt-4o` | $0.75 |
| Documentacion | 5-10 | $0.05 - $0.15 | `gpt-4o-mini` | $0.30 |
| Refactoring complejo | 15-30 | $0.20 - $1.00 | `claude-sonnet-4-6` | $2.00 |
| Feature nueva grande | 20-40 | $0.50 - $2.00 | `gpt-4.1` | $3.00 |

**Nota**: estos costes son para una ejecucion unica del agente. Las features avanzadas (Ralph Loop, Parallel, etc.) multiplican estos valores como se describe en la siguiente seccion.

---

## Multiplicadores de coste en features avanzadas

Las features avanzadas de Architect ejecutan multiples llamadas al LLM internamente. Es crucial tener en cuenta estos multiplicadores al establecer presupuestos.

### Ralph Loop (iteraciones)

Cada iteracion del Ralph Loop ejecuta un agente completo desde cero (contexto limpio). El coste se multiplica por el numero de iteraciones.

```
coste_ralph = coste_base * N_iteraciones
```

Ejemplo: una tarea con coste base de $0.30 y `--max-iterations 5` puede costar hasta $1.50.

```bash
architect loop "implementa feature X" --check "pytest" --max-iterations 5 --budget 2.00
```

### Parallel (workers)

Cada worker en ejecucion paralela es un subproceso completo de `architect run` en un git worktree aislado. El coste se multiplica por el numero de workers.

```
coste_parallel = coste_base * N_workers
```

Ejemplo: 3 workers con coste base de $0.20 cada uno = $0.60 total.

```bash
architect parallel --budget-per-worker 0.50
```

### Auto-review

La revision automatica anade al menos una llamada extra al LLM para analizar el diff generado. Si se detectan issues y se activa un fix pass, se anade una ejecucion adicional del agente.

```
coste_review = coste_base + coste_review_call + (coste_fix_pass si hay issues)
```

Estimacion: +10-30% sobre el coste base.

### Self-evaluation

La autoevaluacion del agente anade llamadas extra dependiendo del modo:

- **basic**: +1 llamada al LLM al final de la ejecucion.
- **full**: +1 llamada por reintento (hasta `max_retries` reintentos).

```
coste_eval_basic = coste_base + 1_llamada_eval
coste_eval_full  = coste_base + N_reintentos * 1_llamada_eval
```

### Compresion de contexto

Cuando el contexto del agente crece demasiado, se activa la compresion automatica que resume el historial. Esto requiere una llamada extra al LLM.

```
coste_compresion = coste_base + N_compresiones * 1_llamada_summary
```

### Formula general de estimacion

Para estimar el coste total de una ejecucion compleja:

```
coste_total = (coste_base + eval_calls + compression_calls + review_calls) * loop_factor * parallel_factor

Donde:
  coste_base       = steps * tokens_promedio * precio_por_token
  eval_calls       = 0 (sin eval), 1 (basic), o N (full con reintentos)
  compression_calls= numero de veces que se activa compression
  review_calls     = 0 (sin review), 1-2 (con review)
  loop_factor      = 1 (sin Ralph), o N (iteraciones de Ralph)
  parallel_factor  = 1 (sin parallel), o N (numero de workers)
```

**Ejemplo completo**: refactoring complejo (~$0.40 base) con self-eval basic (+$0.05), auto-review (+$0.08), en Ralph Loop de 3 iteraciones:

```
($0.40 + $0.05 + $0.08) * 3 = $1.59
Budget recomendado: $2.00
```

---

## Estrategias de optimizacion

### 1. Seleccionar el modelo adecuado para cada tarea

No todas las tareas requieren el modelo mas potente. Usar `gpt-4o-mini` o `claude-haiku-4-5` para tareas de review y documentacion puede reducir costes en un 90% respecto a `gpt-4o`.

```yaml
# architect.yaml — modelo economico por defecto
llm:
  model: gpt-4o-mini

# Sobreescribir para tareas que requieren mas capacidad
# architect run "refactoring complejo" --model gpt-4o
```

### 2. Presupuesto como red de seguridad

Siempre establecer un presupuesto. No como objetivo de gasto, sino como proteccion contra ejecuciones que se disparan:

```yaml
costs:
  budget_usd: 2.00      # Maximo absoluto
  warn_at_usd: 1.50     # Aviso al 75%
```

En CI/CD es especialmente importante para evitar costes inesperados:

```bash
architect run "$TASK" --budget 1.00 --confirm-mode yolo
```

### 3. Mejorar la calidad del prompt

Un prompt claro y especifico reduce el numero de steps que necesita el agente. Menos steps = menos llamadas al LLM = menor coste.

Comparativa:
- Prompt vago: "arregla los bugs" -- 15-20 steps, $0.40
- Prompt preciso: "corrige el null check en `auth.py:42` que causa crash cuando `user.email` es None" -- 3-5 steps, $0.08

### 4. Gestion del contexto

Configurar la compresion de contexto para evitar que los prompts crezcan indefinidamente:

```yaml
agent:
  max_steps: 25
  context:
    summarize_after_steps: 15    # Comprimir contexto despues de N steps
    max_tool_result_tokens: 4000 # Limitar resultados de herramientas
```

Menos tokens de contexto = menor coste por step.

### 5. Modelos locales para desarrollo

Para iteracion rapida durante desarrollo, usar Ollama con un modelo local elimina completamente el coste de API:

```bash
export ARCHITECT_MODEL=ollama/llama3
export ARCHITECT_API_BASE=http://localhost:11434
architect run "experimenta con esta logica" --show-costs
```

### 6. Prompt caching para despliegues de equipo

En entornos donde multiples desarrolladores o pipelines de CI ejecutan Architect con el mismo system prompt, activar prompt caching reduce el coste agregado significativamente:

```yaml
llm:
  model: claude-sonnet-4-6
  prompt_caching: true
```

---

## Monitorizacion para equipos

### Salida de --show-costs

Al usar `--show-costs`, Architect muestra un resumen al finalizar:

```
Costes: $0.0342 (8,450 in / 2,100 out / 3,200 cached)
```

Este formato compacto muestra: coste total, tokens de input, tokens de output, y tokens cacheados (si los hay).

### Salida JSON

Cuando se usa `--json`, la salida incluye un bloque de costes detallado:

```json
{
  "status": "completed",
  "result": "...",
  "costs": {
    "total_input_tokens": 45200,
    "total_output_tokens": 12800,
    "total_cached_tokens": 18000,
    "total_tokens": 58000,
    "total_cost_usd": 0.042,
    "by_source": {
      "agent": 0.038,
      "eval": 0.004
    }
  }
}
```

### Reportes con costes

Los reportes generados con `--report` incluyen informacion de costes:

```bash
# Reporte JSON con costes incluidos
architect run "tarea" --report json --report-file report.json --show-costs

# Reporte Markdown para documentacion
architect run "tarea" --report markdown --report-file report.md
```

### Agregacion de costes en CI

Para agregar costes a traves de multiples ejecuciones en CI/CD, se puede parsear la salida JSON:

```bash
# En un pipeline de CI
architect run "$TASK" --json --budget 1.00 > result.json

# Extraer coste
jq '.costs.total_cost_usd' result.json
```

Para mantener un registro historico, se puede enviar a un sistema de metricas o simplemente acumular en un archivo:

```bash
COST=$(architect run "$TASK" --json | jq '.costs.total_cost_usd')
echo "$(date -Iseconds) $TASK $COST" >> costs.log
```

### Alertas de presupuesto con hooks

Architect soporta hooks de `budget_warning` que se ejecutan cuando el gasto acumulado alcanza el umbral de aviso:

```yaml
costs:
  budget_usd: 2.00
  warn_at_usd: 1.50

hooks:
  budget_warning:
    - run: "echo 'ALERTA: presupuesto al 75%' | slack-notify"
    - run: "curl -X POST https://monitoring.example.com/alert -d 'budget_warning'"
```

Esto permite integrar alertas de coste con sistemas de notificacion del equipo (Slack, PagerDuty, webhooks custom, etc.).

---

## Modelos locales -- coste cero

### Configuracion de Ollama

[Ollama](https://ollama.ai) permite ejecutar modelos de lenguaje localmente sin ningun coste de API. Architect lo soporta nativamente a traves de LiteLLM.

**Instalacion de Ollama**:

```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3
ollama pull codellama
```

**Configuracion de Architect**:

```yaml
llm:
  model: ollama/llama3
  api_base: http://localhost:11434
  timeout: 120   # Modelos locales pueden ser mas lentos
```

O mediante variables de entorno:

```bash
export ARCHITECT_MODEL=ollama/llama3
export ARCHITECT_API_BASE=http://localhost:11434
architect run "tu tarea"
```

### Precios registrados

Todos los modelos que matcheen el prefijo `ollama` tienen precio $0.00 en la tabla de precios:

```json
{
  "ollama": {
    "input_per_million": 0.0,
    "output_per_million": 0.0,
    "cached_input_per_million": 0.0
  }
}
```

### Limitaciones

| Aspecto | Modelos cloud | Modelos locales (Ollama) |
|---|---|---|
| Coste | Variable segun uso | $0 siempre |
| Calidad | Alta (GPT-4o, Claude) | Variable, generalmente inferior |
| Velocidad | Rapida (servidores GPU) | Depende del hardware local |
| Contexto maximo | 128K-200K tokens | 4K-32K tipicamente |
| Tool calling | Completo | Soporte limitado en algunos modelos |
| Disponibilidad | Requiere internet | Funciona offline |

### Recomendaciones de uso

- **Desarrollo y experimentacion**: ideal para iterar en prompts y flujos sin coste.
- **Tareas simples**: renombrado de variables, formateo, generacion de boilerplate.
- **No recomendado para**: refactoring complejo, analisis de arquitectura, o cualquier tarea donde la calidad del output sea critica.
- **Combinacion optima**: usar Ollama durante desarrollo local y un modelo cloud en CI/CD con presupuesto.

```bash
# Desarrollo local — coste $0
ARCHITECT_MODEL=ollama/llama3 ARCHITECT_API_BASE=http://localhost:11434 architect run "prototipa esto"

# CI/CD — modelo cloud con presupuesto
architect run "implementa feature" --budget 1.00 --show-costs
```

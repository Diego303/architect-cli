# Prompt Engineering para Architect CLI

> Guia completa para escribir prompts efectivos, archivos `.architect.md` y skills que maximicen
> la calidad del resultado y minimicen el coste de ejecucion.

---

## 1. Por que importa la calidad del prompt

Architect CLI es una herramienta donde tu interfaz principal es el **lenguaje natural**. La calidad
del prompt que escribes determina directamente tres variables:

| Variable | Prompt vago | Prompt preciso |
|----------|-------------|----------------|
| **Pasos del agente** | 15-20 (busca, prueba, retrocede) | 5-8 (va directo) |
| **Coste en tokens** | $0.30-0.80 | $0.05-0.15 |
| **Calidad del resultado** | Parcial, requiere iteraciones | Completo en una pasada |

La relacion es directa: un prompt ambiguo obliga al agente a gastar pasos explorando, leyendo
archivos que no necesita, y tomando decisiones que podrias haber especificado. Un prompt preciso
le permite al agente ejecutar un plan lineal sin retrocesos.

El coste se multiplica rapidamente. Cada paso implica una llamada al LLM con todo el contexto
acumulado. En el step 1, el LLM procesa ~3,000 tokens de contexto. En el step 15, puede estar
procesando ~40,000 tokens. Los pasos finales son exponencialmente mas caros que los iniciales.

---

## 2. Que ve el LLM — Anatomia del contexto

Antes de escribir un prompt, es fundamental entender **que informacion ya tiene el LLM** cuando
recibe tu tarea. El contexto se ensambla en capas:

```
┌─────────────────────────────────────────────────────────────────┐
│  SYSTEM MESSAGE (mensaje de sistema)                            │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 1. Agent Prompt (BUILD_PROMPT / PLAN_PROMPT / ...)       │  │
│  │    - Proceso de trabajo del agente                       │  │
│  │    - Jerarquia de herramientas de edicion                │  │
│  │    - Herramientas de busqueda                            │  │
│  │    - Reglas de comportamiento                            │  │
│  │    ~600-800 tokens                                       │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 2. Repo Tree (inyectado por RepoIndexer)                 │  │
│  │    - Total archivos, lineas, lenguajes                   │  │
│  │    - Arbol de directorios completo                       │  │
│  │    ~500-3,000 tokens (segun tamanio del repo)            │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 3. Skills activas (solo las que matchean por glob)       │  │
│  │    - Contenido de SKILL.md relevantes                    │  │
│  │    ~0-1,000 tokens por skill                             │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 4. Memoria procedural (.architect/memory.md)             │  │
│  │    - Correcciones de sesiones anteriores                 │  │
│  │    ~0-500 tokens                                         │  │
│  └───────────────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ 5. Instrucciones del proyecto (.architect.md)            │  │
│  │    - Convenciones, patrones, restricciones               │  │
│  │    ~0-2,000 tokens                                       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  USER MESSAGE (tu prompt)                                       │
│  ~50-500 tokens                                                 │
├─────────────────────────────────────────────────────────────────┤
│  CONVERSATION HISTORY (se acumula durante la ejecucion)         │
│  - Tool calls del LLM                                           │
│  - Tool results (truncados a max_tool_result_tokens)            │
│  - Se comprime despues de summarize_after_steps pasos           │
│  - Hard limit: max_context_tokens (default 80,000)              │
│  ~0-60,000 tokens                                               │
└─────────────────────────────────────────────────────────────────┘
```

### Por que esto importa

El LLM ya llega con **1,500-7,000 tokens de contexto base** antes de leer tu prompt. Esto
significa que:

1. **No necesitas repetir** lo que el arbol del repo ya dice. El agente ya sabe que archivos
   existen, en que lenguajes estan y cuantas lineas tienen.

2. **No necesitas explicar como usar las herramientas.** El BUILD_PROMPT ya le dice que use
   `edit_file` antes que `write_file`, que lea antes de editar, y que verifique despues.

3. **Cada token de tu prompt compite** por espacio con el historial de conversacion. Un prompt
   de 2,000 tokens deja menos margen para pasos complejos que uno de 200 tokens.

4. **El `.architect.md` se repite en CADA llamada al LLM.** Si tiene 500 lineas, eso son
   ~2,000 tokens multiplicados por cada step. En una sesion de 10 steps: 20,000 tokens solo
   en instrucciones de proyecto.

### Idioma de los prompts (v1.1.0)

Los system prompts de los agentes (`build`, `plan`, `resume`, `review`) se adaptan al idioma
configurado (`language: en` o `language: es`). Si usas español, el agente recibe instrucciones
en español y tiende a responder en español. Si usas inglés (default), las respuestas del agente
serán en inglés. Esto es independiente del idioma de TU prompt — puedes escribir en español
aunque `language: en`, y el agente entenderá igualmente.

### Los cuatro agentes y sus prompts

Architect tiene cuatro agentes con prompts diferentes. Saber cual se usa afecta como escribir
tu tarea:

| Agente | Cuando se usa | Puede modificar archivos | Enfoque |
|--------|---------------|--------------------------|---------|
| `build` | `architect run` (default) | Si | Analizar, planificar, ejecutar, verificar |
| `plan` | `architect run -a plan` | No | Solo lectura y analisis |
| `resume` | `architect resume <id>` | No | Reanudar sesion interrumpida |
| `review` | `architect run -a review` | No | Buscar bugs, seguridad, mejoras |

El agente **build** sigue un flujo especifico: "lee primero, modifica despues, verifica tercero".
Su jerarquia de edicion es:

1. `edit_file` (str_replace exacto) -- preferido para cambios pequenios
2. `apply_patch` (unified diff) -- para cambios en multiples secciones
3. `write_file` -- solo para archivos nuevos o reescrituras completas

Tu prompt debe alinearse con este flujo, no contradecirlo.

---

## 3. Patrones de prompts efectivos

### Patron 1: Tarea especifica con archivos explicitos

Cuando sabes exactamente que archivo modificar, dilo. El agente ahorra 2-3 pasos de busqueda.

```
architect run "Refactoriza la funcion validate_email en src/utils/validators.py
para usar regex en vez de split. Mantiene los mismos casos de retorno (True/False)
y los mensajes de error actuales."
```

**Por que funciona:** El agente sabe el archivo, la funcion, el cambio y las restricciones.
Va directo: `read_file` -> `edit_file` -> verificar.

### Patron 2: Tarea con criterios de exito

Cuando no quieres listar cada cambio pero si defines que significa "terminado":

```
architect run "Aniade tests unitarios para src/auth/service.py que cubran:
- Login exitoso con credenciales validas
- Contrasenia incorrecta retorna 401
- Usuario no existe retorna 404
- Token expirado retorna 401
- Rate limiting despues de 5 intentos fallidos
Usa pytest y mocks para la base de datos."
```

**Por que funciona:** Los criterios de exito son concretos y verificables. El agente puede
evaluar si termino o no. Sin ambiguedad sobre alcance.

### Patron 3: Tarea con restricciones explicitas

Cuando hay cosas que el agente NO debe hacer, dilas explicitamente:

```
architect run "Migra las llamadas HTTP de requests a httpx en src/api/client.py.
Restricciones:
- NO cambies la API publica de la clase HttpClient (mismos metodos, mismos parametros)
- NO cambies los tests existentes (deben seguir pasando)
- Usa httpx sincrono, no async"
```

**Por que funciona:** Las restricciones evitan que el agente tome decisiones de disenio que
no quieres. Sin ellas, podria cambiar la API publica "porque queda mejor con httpx async".

### Patron 4: Tarea con formato de output

Para tareas de generacion donde el formato importa:

```
architect run "Genera el archivo docs/API.md con documentacion de la API REST.
Estructura requerida:
## Autenticacion (explica Bearer token)
## Endpoints (tabla: metodo, path, descripcion, auth requerida)
## Errores (codigos HTTP y formato del body)
## Ejemplos (curl para cada endpoint)
Basa la informacion en los archivos de src/api/routes/"
```

**Por que funciona:** El formato esta definido. El agente no tiene que decidir como organizar
el documento.

### Patron 5: Tarea incremental de exploracion

Cuando no sabes exactamente que hay que cambiar pero si que buscar:

```
architect run "Lee todos los endpoints en src/api/routes/ y corrige los que no
validan el input del usuario. Cada endpoint debe:
1. Validar que los campos requeridos existen
2. Validar tipos (no aceptar string donde se espera int)
3. Retornar 422 con mensaje descriptivo si la validacion falla
Usa los validadores existentes de src/utils/validators.py si existen."
```

**Por que funciona:** El agente tiene un patron claro de que buscar y como corregirlo.
La referencia a validadores existentes evita que reinvente la rueda.

---

## 4. Anti-patrones — Que NO hacer

### Anti-patron 1: Prompts vagos

```
# MAL
architect run "mejora el codigo"

# MAL
architect run "hazlo mas limpio"

# MAL
architect run "refactoriza"
```

**Problema:** "Mejorar" no tiene definicion. El agente leera archivos al azar, hara cambios
cosmeticos, y consumira 15+ pasos sin un objetivo claro. Resultado: cambios dispersos que
pueden romper cosas, coste alto, calidad baja.

**Solucion:** Siempre especifica QUE mejorar, EN DONDE, y COMO sabras que esta mejorado.

### Anti-patron 2: Multi-objetivo en un solo prompt

```
# MAL
architect run "Refactoriza el modulo auth, aniade tests para todos los endpoints,
actualiza la documentacion del README, optimiza las queries de la base de datos
y configura CI/CD con GitHub Actions"
```

**Problema:** Son 5 tareas independientes. El agente intentara hacer todo, se quedara sin
contexto a mitad, y el resultado sera parcial en cada tarea. Peor: si falla en la tarea 3,
las tareas 4 y 5 ni se intentan.

**Solucion:** Divide en ejecuciones separadas o usa un pipeline YAML:

```bash
# Opcion A: Ejecuciones separadas
architect run "Refactoriza el modulo auth separando validacion de sesion"
architect run "Aniade tests para los endpoints de src/api/routes/"
architect run "Actualiza README.md con la nueva estructura de auth"

# Opcion B: Pipeline YAML (ver seccion 7)
architect pipeline workflow.yaml
```

### Anti-patron 3: Contradecir el agente

```
# MAL — lucha contra la jerarquia de edicion del BUILD_PROMPT
architect run "Para todos los cambios usa write_file, nunca edit_file"

# MAL — desactiva la verificacion que el agente necesita
architect run "No ejecutes tests despues de los cambios"

# MAL — impide la exploracion que necesita
architect run "No leas archivos, solo escribe los cambios directamente"
```

**Problema:** El BUILD_PROMPT ya establece que `edit_file` es preferido, que hay que verificar
despues de cada cambio, y que hay que leer antes de editar. Contradecir estas reglas confunde
al LLM, que recibe instrucciones opuestas en el mismo contexto.

**Solucion:** Trabaja CON el agente, no contra el. Si necesitas write_file para un archivo
nuevo, simplemente describe la tarea y el agente elegira la herramienta correcta.

### Anti-patron 4: Prompts gigantes con contexto innecesario

```
# MAL — 500 lineas de contexto que el agente no necesita
architect run "Aqui esta el historial completo del proyecto desde 2019,
las decisiones de arquitectura, las minutas de las reuniones, el roadmap
para 2027... [500 lineas mas] ...por cierto, cambia el color del boton
a azul en src/components/Button.tsx"
```

**Problema:** Cada token del prompt se procesa en CADA llamada al LLM. 500 lineas de contexto
irrelevante consumen ~2,000 tokens por step. En 10 steps: 20,000 tokens desperdiciados. Ademas,
el LLM puede distraerse con el contexto y hacer cambios no solicitados.

**Solucion:** Solo incluye lo que el agente necesita para esta tarea especifica:

```
architect run "Cambia el color del boton primario a azul (#0066CC) en
src/components/Button.tsx. Solo el variant='primary'."
```

### Anti-patron 5: No especificar archivos cuando los conoces

```
# MAL — el agente gastara 3-4 pasos buscando
architect run "Corrige el bug de autenticacion"

# BIEN — va directo
architect run "Corrige el bug en src/auth/middleware.py donde el token JWT
no se valida cuando viene en query params (solo valida el header Authorization)"
```

**Problema:** Si tu sabes que el bug esta en `middleware.py`, no obligues al agente a buscarlo.
Cada paso de busqueda (grep, search_code, read_file de archivos irrelevantes) consume tokens
y tiempo.

---

## 5. Escribir .architect.md efectivos

El archivo `.architect.md` (tambien `AGENTS.md` o `CLAUDE.md`) se inyecta en el system prompt
de **cada llamada al LLM**, en cada step, de cada sesion. Esto lo convierte en el mecanismo
mas poderoso y mas costoso de configuracion.

### Que incluir

1. **Convenciones de codigo** que no son evidentes desde el codigo:

```markdown
## Convenciones

- Imports ordenados: stdlib, terceros, locales (separados por linea en blanco)
- Nombres de variables en snake_case, clases en PascalCase
- Funciones publicas siempre con docstring (formato Google)
- No usar `print()`, usar `logger.info()` de structlog
```

2. **Bibliotecas preferidas** (cuando hay alternativas):

```markdown
## Dependencias

- HTTP client: httpx (no requests)
- Validacion: pydantic v2 (no dataclasses para inputs externos)
- Tests: pytest + pytest-mock (no unittest)
- Formato de fechas: siempre ISO 8601 con timezone
```

3. **Anti-patrones conocidos del proyecto**:

```markdown
## Prohibido

- NO usar `import *`
- NO queries SQL sin parametros (siempre prepared statements)
- NO escribir secretos en codigo (usar variables de entorno)
- NO funciones de mas de 50 lineas
```

4. **Estructura esperada** (cuando no es obvia):

```markdown
## Estructura

- Nuevos endpoints van en src/api/routes/<recurso>.py
- Modelos de DB van en src/models/<recurso>.py
- Schemas Pydantic van en src/schemas/<recurso>.py
- Tests espejo: tests/test_<modulo>/test_<archivo>.py
```

### Que NO incluir

- **Lo que el codigo ya dice.** Si tienes un `pyproject.toml` con la version de Python,
  no lo repitas en `.architect.md`. El agente puede leerlo.
- **Documentacion generica.** No copies el README dentro de `.architect.md`.
- **Instrucciones de un solo uso.** "Migra de Flask a FastAPI" no va en `.architect.md`;
  va en el prompt del `architect run`.
- **Historial de cambios.** No es un CHANGELOG.

### Tamanio recomendado

Cada linea se repite en cada step. La matematica:

| Lineas en .architect.md | Tokens/step | Sesion de 10 steps | Sesion de 20 steps |
|--------------------------|-------------|---------------------|--------------------|
| 50 lineas (~200 tokens) | 200 | 2,000 tokens | 4,000 tokens |
| 200 lineas (~800 tokens) | 800 | 8,000 tokens | 16,000 tokens |
| 500 lineas (~2,000 tokens) | 2,000 | 20,000 tokens | 40,000 tokens |

**Recomendacion:** Mantenlo por debajo de 500 lineas. Idealmente entre 50-150 lineas.
Si necesitas mas, mueve instrucciones especificas a **skills** (se activan solo cuando
los archivos coinciden).

### Ejemplo completo: Proyecto Django

```markdown
# Instrucciones del Proyecto — Mi App Django

## Stack
- Django 5.0, Python 3.12, PostgreSQL 16
- DRF para API REST, Celery para tareas async
- pytest-django para tests

## Convenciones de codigo
- Modelos: verbose_name en espaniol, Meta.ordering siempre definido
- Views: usar class-based views (APIView de DRF), no function-based
- Serializers: validacion en validate_<field>(), nunca en la view
- URLs: kebab-case (api/mis-recursos/), no snake_case
- Permisos: siempre definir permission_classes, nunca dejar AllowAny en produccion

## Estructura de archivos nuevos
- apps/<nombre>/models.py — Modelos de DB
- apps/<nombre>/serializers.py — Serializers DRF
- apps/<nombre>/views.py — Views/ViewSets
- apps/<nombre>/urls.py — URL patterns
- apps/<nombre>/tests/ — Tests (un archivo por modulo)
- apps/<nombre>/admin.py — Configuracion de admin

## Reglas de seguridad
- NUNCA hardcodear secretos, usar django.conf.settings
- Todos los endpoints autenticados por defecto (IsAuthenticated)
- Filtros de queryset: siempre filtrar por usuario autenticado
- No usar .raw() ni queries SQL directas

## Tests
- Cada view debe tener tests de: 200 OK, 401 no auth, 403 forbidden, 404 not found
- Usar factory_boy para fixtures, no json fixtures
- Nombres: test_<accion>_<condicion>_<resultado_esperado>
```

Este ejemplo tiene ~40 lineas, ~160 tokens. Es conciso, accionable y cubre lo que el
codigo no dice por si solo.

---

## 6. Escribir Skills efectivas

Las skills son instrucciones contextuales que se activan **solo cuando el agente trabaja con
archivos que coinciden con sus globs**. A diferencia de `.architect.md` (que se inyecta siempre),
las skills son selectivas.

### Cuando usar skills vs .architect.md

| Criterio | .architect.md | Skill |
|----------|---------------|-------|
| Se aplica a todo el proyecto | Si | No |
| Se activa solo para ciertos archivos | No | Si |
| Se repite en cada step | Siempre | Solo si hay archivos matching |
| Coste en tokens | Constante | Variable |

**Usa `.architect.md`** para convenciones globales (formato de imports, prohibiciones, stack).
**Usa skills** para instrucciones especificas de un tipo de archivo (como escribir modelos,
como escribir tests, como escribir endpoints).

### Estructura de una skill

Las skills se almacenan en `.architect/skills/<nombre>/SKILL.md` con frontmatter YAML:

```
.architect/
  skills/
    django-models/
      SKILL.md
    api-endpoints/
      SKILL.md
```

### Ejemplo: Skill para modelos Django

`.architect/skills/django-models/SKILL.md`:

```markdown
---
name: django-models
description: Convenciones para modelos Django del proyecto
globs:
  - "*/models.py"
  - "*/models/*.py"
---

## Modelos Django — Convenciones

### Estructura de cada modelo
1. Campos del modelo (ordenados: PK, FKs, campos de datos, timestamps)
2. Meta class (ordering, verbose_name, verbose_name_plural, constraints)
3. __str__
4. clean() si hay validacion custom
5. Metodos de negocio
6. Managers customizados al final del archivo

### Campos obligatorios
- Todos los modelos deben tener `created_at` y `updated_at` (auto_now_add, auto_now)
- Usar `models.UUIDField` como PK en vez de AutoField
- ForeignKey siempre con `on_delete` explicito y `related_name`

### Migraciones
- Despues de modificar un modelo, ejecutar `python manage.py makemigrations`
- Verificar que la migracion generada es correcta
```

Esta skill solo se inyecta cuando el agente trabaja con archivos `models.py`. Si la tarea
es editar un template HTML, esta skill no consume tokens.

### Ejemplo: Skill para endpoints API

`.architect/skills/api-endpoints/SKILL.md`:

```markdown
---
name: api-endpoints
description: Convenciones para endpoints de API REST
globs:
  - "*/views.py"
  - "*/viewsets.py"
  - "*/routes.py"
  - "*/routes/*.py"
---

## Endpoints API — Convenciones

### Estructura de un ViewSet
1. queryset y serializer_class
2. permission_classes
3. filterset_fields / search_fields
4. Acciones CRUD (list, create, retrieve, update, destroy)
5. Acciones custom con @action decorator

### Respuestas
- 200: operacion exitosa con datos
- 201: recurso creado (incluir Location header)
- 204: eliminacion exitosa (sin body)
- 400: error de validacion (body con campo: [errores])
- 401: no autenticado
- 403: sin permisos
- 404: recurso no existe

### Paginacion
- Siempre usar LimitOffsetPagination
- Default: limit=20, max_limit=100
```

---

## 7. Prompts para features avanzadas

Las features avanzadas de architect (Ralph Loop, Pipelines, Parallel, Review) tienen
caracteristicas especificas que afectan como escribir prompts para ellas.

### Ralph Loop (`architect loop`)

El Ralph Loop ejecuta iteraciones del agente hasta que todos los checks pasen. **Cada iteracion
tiene contexto LIMPIO**: el agente no recibe el historial de conversacion de iteraciones anteriores.
Solo recibe:

- La tarea/spec original
- El diff acumulado de iteraciones anteriores
- Los errores de la ultima iteracion
- Un progress.md auto-generado

**Implicaciones para el prompt:**

```bash
# BIEN — tarea autocontenida, checks claros
architect loop \
  "Implementa la funcion parse_csv en src/parser.py que lea un CSV,
   valide que las columnas 'name' y 'email' existen, y retorne una
   lista de diccionarios. Si falta una columna, lanza ValueError
   con mensaje descriptivo." \
  --check "python -m pytest tests/test_parser.py -v" \
  --max-iterations 10

# MAL — depende de contexto que el agente no tiene entre iteraciones
architect loop \
  "Sigue con lo que estabas haciendo antes" \
  --check "pytest"
```

Escribe la tarea como si fuera la **primera vez** que el agente la ve, porque en cada
iteracion, lo es. Los checks deben ser comandos que retornan exit code 0 cuando la tarea
esta completa.

### Pipelines (`architect pipeline`)

Los pipelines ejecutan steps secuenciales. Cada step tiene su propio agente con contexto limpio.
Los steps se comunican mediante `{{variables}}`.

```yaml
name: feature-completa
variables:
  modulo: auth
  tabla: users

steps:
  - name: crear-modelo
    prompt: |
      Crea el modelo {{tabla}} en apps/{{modulo}}/models.py con campos:
      username (CharField, unique), email (EmailField, unique),
      is_active (BooleanField, default True), created_at, updated_at.
    checkpoint: true

  - name: crear-serializer
    prompt: |
      Crea el serializer para el modelo {{tabla}} en
      apps/{{modulo}}/serializers.py. Incluye validacion de email
      unico en validate_email(). Campos: username, email, is_active.

  - name: crear-tests
    prompt: |
      Crea tests para el modelo {{tabla}} y su serializer en
      apps/{{modulo}}/tests/test_{{tabla}}.py. Cubre:
      - Creacion exitosa
      - Email duplicado
      - Username duplicado
      - Serializer validation
    checks:
      - "python -m pytest apps/{{modulo}}/tests/ -v"
```

**Reglas para prompts de pipeline:**

1. Cada prompt debe ser **independiente** — no asumas que el agente recuerda el step anterior
2. Usa `{{variables}}` para datos compartidos entre steps
3. Usa `checkpoint: true` antes de steps destructivos (para poder hacer rollback)
4. Usa `checks` para verificar que el step se completo correctamente

### Parallel (`architect parallel`)

Las ejecuciones paralelas lanzan multiples agentes en worktrees git separados.
**Cada worker es completamente aislado**: no sabe que hacen los otros workers.

```bash
# BIEN — tareas independientes que no se pisan
architect parallel \
  "Aniade validacion de input a src/api/routes/users.py" \
  "Aniade validacion de input a src/api/routes/products.py" \
  "Aniade validacion de input a src/api/routes/orders.py"

# MAL — tareas que modifican los mismos archivos
architect parallel \
  "Refactoriza src/utils.py para usar httpx" \
  "Aniade logging a todas las funciones de src/utils.py"
```

**Reglas para tareas paralelas:**

1. Las tareas deben modificar **archivos diferentes**
2. Cada tarea debe ser autocontenida (no depende del resultado de otra)
3. Los resultados se revisan manualmente antes de mergear (cada worker crea su branch)

### Review (`architect run` con auto-review)

El reviewer recibe solo el diff y la tarea original. Para obtener un review util, se
especifico sobre que quieres que busque:

```yaml
# En .architect.yaml
auto_review:
  enabled: true
  max_fix_passes: 1
```

El reviewer busca por defecto: bugs, seguridad, convenciones, simplificacion y tests
faltantes. Si quieres enfocarlo, ajusta la tarea original para que incluya el contexto
de seguridad o performance que importa.

---

## 8. Ejemplos antes/despues

### Ejemplo 1: Tarea de correccion de bug

**Prompt original (malo):**
```
architect run "Arregla el bug de login"
```

**Problemas:**
- No dice cual bug, en que archivo, ni como se manifiesta
- El agente gastara 5-8 pasos solo buscando donde esta el problema
- Si hay multiples bugs de login, no sabe cual priorizar

**Prompt mejorado:**
```
architect run "En src/auth/login.py, la funcion authenticate() no maneja
el caso donde el usuario existe pero esta desactivado (is_active=False).
Actualmente retorna None (como si no existiera). Debe retornar un error
especifico: raise AccountDisabledError('Cuenta desactivada'). El error
ya esta definido en src/auth/exceptions.py."
```

**Diferencia estimada:**
- Antes: ~12 steps, ~$0.35, resultado incierto
- Despues: ~4 steps, ~$0.08, resultado preciso

---

### Ejemplo 2: Tarea de anadir tests

**Prompt original (malo):**
```
architect run "Aniade tests"
```

**Problemas:**
- Tests para que? Todo el proyecto? Un archivo?
- Que tipo de tests? Unitarios, integracion, e2e?
- Que casos cubrir?

**Prompt mejorado:**
```
architect run "Aniade tests unitarios para src/payments/processor.py.
Casos a cubrir:
1. process_payment() con tarjeta valida retorna PaymentResult(success=True)
2. process_payment() con tarjeta expirada lanza CardExpiredError
3. process_payment() con fondos insuficientes lanza InsufficientFundsError
4. refund() con payment_id valido retorna RefundResult(success=True)
5. refund() con payment_id inexistente lanza PaymentNotFoundError
Usa pytest con mocks para el gateway externo (src/payments/gateway.py)."
```

**Diferencia estimada:**
- Antes: ~15 steps, ~$0.50, tests vagos e incompletos
- Despues: ~6 steps, ~$0.12, 5 tests especificos y utiles

---

### Ejemplo 3: Tarea de refactorizacion

**Prompt original (malo):**
```
architect run "Refactoriza el codigo para que sea mejor"
```

**Problemas:**
- "Mejor" no tiene definicion
- El agente podria cambiar nombres de variables, reorganizar imports, o reescribir funciones
  enteras sin necesidad
- Alto riesgo de romper funcionalidad

**Prompt mejorado:**
```
architect run "Refactoriza src/data/repository.py: extrae las funciones
de consulta SQL (get_users, get_orders, get_products) a una clase
BaseRepository con un metodo generico query(table, filters). Las tres
funciones actuales deben usar BaseRepository internamente. Los tests
existentes en tests/test_repository.py deben seguir pasando sin cambios."
```

**Diferencia estimada:**
- Antes: ~18 steps, ~$0.60, cambios impredecibles
- Despues: ~7 steps, ~$0.15, refactorizacion acotada y segura

---

### Ejemplo 4: Tarea de documentacion

**Prompt original (malo):**
```
architect run "Documenta el proyecto"
```

**Problemas:**
- No define que documentar ni en que formato
- El agente podria generar un README generico, docstrings, o una wiki
- Sin estructura definida, el resultado sera desordenado

**Prompt mejorado:**
```
architect run "Genera docs/deployment.md con guia de despliegue. Secciones:
## Requisitos (Python 3.12, PostgreSQL 16, Redis)
## Variables de entorno (lee .env.example y documenta cada variable)
## Base de datos (migraciones con django manage.py migrate)
## Despliegue local (docker-compose up)
## Despliegue en produccion (gunicorn + nginx, basado en Dockerfile)
Lee los archivos docker-compose.yml, Dockerfile y .env.example como fuente."
```

**Diferencia estimada:**
- Antes: ~10 steps, ~$0.30, documento vago sin estructura
- Despues: ~5 steps, ~$0.10, documento estructurado basado en archivos reales

---

## Resumen de reglas de oro

1. **Se especifico:** archivo + funcion + cambio + restricciones
2. **Define "terminado":** criterios de exito verificables
3. **Una tarea por ejecucion:** divide tareas complejas en pasos
4. **No repitas lo que el agente ya sabe:** el repo tree, las herramientas, el flujo
5. **Mantiene `.architect.md` conciso:** <500 lineas, solo convenciones no obvias
6. **Usa skills para contexto selectivo:** globs para activacion por tipo de archivo
7. **Especifica archivos cuando los conoces:** ahorra pasos de busqueda
8. **Alineate con el agente:** no contradigas el BUILD_PROMPT

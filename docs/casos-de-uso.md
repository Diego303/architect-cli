# Casos de Uso — Architect CLI

Guía práctica de integración de `architect` en flujos de trabajo reales: desarrollo diario, CI/CD, DevOps, QA, documentación y arquitecturas avanzadas con servidores MCP.

---

## Índice

- [¿Qué es architect?](#qué-es-architect)
- [Desarrollo diario](#desarrollo-diario)
  - [Implementar funcionalidades nuevas](#implementar-funcionalidades-nuevas)
  - [Refactorización de código](#refactorización-de-código)
  - [Explorar y entender código desconocido](#explorar-y-entender-código-desconocido)
  - [Revisión de código bajo demanda](#revisión-de-código-bajo-demanda)
  - [Generar documentación desde código](#generar-documentación-desde-código)
  - [Debugging asistido por IA](#debugging-asistido-por-ia)
  - [Scaffolding de proyectos](#scaffolding-de-proyectos)
- [CI/CD y automatización](#cicd-y-automatización)
  - [Review automática en Pull Requests](#review-automática-en-pull-requests)
  - [Auditoría de seguridad en pipeline](#auditoría-de-seguridad-en-pipeline)
  - [Generación de changelogs](#generación-de-changelogs)
  - [Autofix de linting en CI](#autofix-de-linting-en-ci)
  - [Validación de migraciones](#validación-de-migraciones)
- [QA y Calidad](#qa-y-calidad)
  - [Generación de tests unitarios](#generación-de-tests-unitarios)
  - [Análisis de cobertura y tests faltantes](#análisis-de-cobertura-y-tests-faltantes)
  - [Quality gate con self-evaluation](#quality-gate-con-self-evaluation)
  - [Revisión de contratos de API](#revisión-de-contratos-de-api)
- [DevOps](#devops)
  - [Generación y revisión de IaC](#generación-y-revisión-de-iac)
  - [Análisis de Dockerfiles y Helm charts](#análisis-de-dockerfiles-y-helm-charts)
  - [Revisión de configuraciones de seguridad](#revisión-de-configuraciones-de-seguridad)
- [Documentación técnica](#documentación-técnica)
  - [Documentación de APIs](#documentación-de-apis)
  - [Onboarding de nuevos desarrolladores](#onboarding-de-nuevos-desarrolladores)
  - [Análisis de decisiones de arquitectura](#análisis-de-decisiones-de-arquitectura)
- [Arquitecturas avanzadas con MCP](#arquitecturas-avanzadas-con-mcp)
  - [Agente de desarrollo con múltiples MCP servers](#agente-de-desarrollo-con-múltiples-mcp-servers)
  - [Architect como MCP server (implementador de código)](#architect-como-mcp-server-implementador-de-código)
  - [Pipeline multi-agente](#pipeline-multi-agente)
  - [Integración con LiteLLM Proxy para equipos](#integración-con-litellm-proxy-para-equipos)
- [AIOps y MLOps](#aiops-y-mlops)
  - [Revisión de pipelines de ML](#revisión-de-pipelines-de-ml)
  - [Generación de código de feature engineering](#generación-de-código-de-feature-engineering)
  - [Análisis de drift en configuraciones](#análisis-de-drift-en-configuraciones)
- [Ralph Loop, Pipelines y Parallel (v4-C)](#ralph-loop-pipelines-y-parallel-v4-c)
  - [Iteración automática hasta que los tests pasen](#iteración-automática-hasta-que-los-tests-pasen)
  - [Pipeline CI completo: implementar → testear → revisar](#pipeline-ci-completo-implementar--testear--revisar)
  - [Competición de modelos en paralelo](#competición-de-modelos-en-paralelo)
  - [Generación de tests en paralelo](#generación-de-tests-en-paralelo)
  - [CI/CD con Ralph Loop y reportes](#cicd-con-ralph-loop-y-reportes)
  - [Auto-review en CI](#auto-review-en-ci)
- [Patrones de configuración](#patrones-de-configuración)
  - [Configuración para CI headless](#configuración-para-ci-headless)
  - [Configuración para desarrollo local](#configuración-para-desarrollo-local)
  - [Agentes custom por equipo](#agentes-custom-por-equipo)
- [Costes de referencia](#costes-de-referencia)

---

## ¿Qué es architect?

`architect` es una CLI headless que conecta un LLM a herramientas de sistema de archivos y ejecución de comandos. El usuario describe una tarea en lenguaje natural, y el agente itera de forma autónoma: lee código, planifica cambios, edita archivos, ejecuta tests y verifica su propio trabajo.

**Capacidades reales:**

| Capacidad | Detalle |
|-----------|---------|
| Lectura inteligente | Lee archivos, busca con regex/grep/glob, indexa la estructura del proyecto |
| Edición precisa | `edit_file` (str_replace), `apply_patch` (unified diff), `write_file` (archivos nuevos) |
| Ejecución de comandos | Tests, linters, compiladores, git, scripts — con 4 capas de seguridad |
| Auto-verificación | Hooks post-edición (ruff, mypy, eslint) cuyo resultado vuelve al agente para auto-corregir |
| Tools remotas (MCP) | Conecta a servidores MCP para GitHub, Jira, bases de datos o cualquier API |
| Control de costes | Budget por ejecución, tracking de tokens, alertas |
| Salida estructurada | `--json` para integrar con pipelines, `--quiet` para scripting |
| Seguridad por diseño | Path traversal prevention, blocklist de comandos, confirmación de ops sensibles |

**Cuatro agentes por defecto:**

| Agente | Capacidad | Tools | Pasos máx. |
|--------|-----------|-------|------------|
| `build` | Lee + edita + ejecuta | Todas (filesystem, search, commands, patch) | 50 |
| `plan` | Lee + planifica (sin modificar) | Solo lectura (read, list, search, grep, find) | 20 |
| `review` | Inspecciona código y da feedback | Solo lectura | 20 |
| `resume` | Resume y sintetiza información | Solo lectura | 15 |

---

## Desarrollo diario

### Implementar funcionalidades nuevas

El caso de uso más directo: describir qué necesitas y que el agente `build` lo implemente.

```bash
# Añadir validación de email a un modelo existente
architect run "en user.py, añade validación de email al campo email \
  usando un regex estándar. Si el email es inválido, lanza ValueError \
  con mensaje descriptivo. Añade tests en test_user.py." \
  --mode yolo

# Añadir un nuevo endpoint REST
architect run "añade un endpoint GET /api/v1/health que retorne \
  {status: 'ok', version: '1.0.0'} con código 200. \
  Usa el mismo patrón que los endpoints existentes en routes/" \
  --mode yolo --self-eval basic

# Implementar un patrón de diseño
architect run "refactoriza payment_processor.py para usar el patrón \
  Strategy. Extrae cada método de pago (stripe, paypal, transfer) \
  a su propia clase que implemente PaymentStrategy." \
  --mode yolo -v
```

**Qué ocurre internamente:**
1. El agente lee el árbol del proyecto (indexer) y entiende la estructura.
2. Busca archivos relevantes con `search_code`/`grep`.
3. Lee los archivos a modificar.
4. Planifica los cambios internamente.
5. Edita paso a paso con `edit_file` (preferido) o `write_file` (archivos nuevos).
6. Si hay hooks configurados (ruff, mypy), se ejecutan tras cada edición.
7. Si un hook falla, el agente ve el error y corrige automáticamente.
8. Opcionalmente, verifica el resultado con `--self-eval basic`.

### Refactorización de código

```bash
# Renombrar y reorganizar
architect run "mueve todas las funciones de utils.py a módulos separados: \
  string_utils.py, date_utils.py y file_utils.py. Actualiza todos los \
  imports en el proyecto." \
  --mode yolo --allow-commands

# Migrar de un patrón a otro
architect run "migra las clases de config/ de dataclasses a Pydantic v2. \
  Mantén los defaults existentes y añade model_config = {'extra': 'forbid'}" \
  --mode yolo

# Eliminar código muerto
architect run "analiza src/ y elimina funciones, imports y variables \
  que no se usen en ningún otro archivo del proyecto" \
  --mode yolo --self-eval full
```

### Explorar y entender código desconocido

Ideal para incorporarse a un proyecto existente o analizar una librería.

```bash
# Resumen rápido de un proyecto
architect run "explica la arquitectura de este proyecto: \
  qué hace, cómo está organizado, qué tecnologías usa \
  y cuáles son los flujos principales" \
  -a resume --quiet

# Entender un módulo complejo
architect run "explica cómo funciona el sistema de autenticación: \
  desde el login hasta la validación del token. \
  Incluye los archivos involucrados y el flujo de datos" \
  -a resume

# Analizar dependencias
architect run "lista todas las dependencias externas del proyecto, \
  para qué se usa cada una, y si hay alguna duplicada o innecesaria" \
  -a plan --json | jq -r '.final_output'
```

### Revisión de código bajo demanda

```bash
# Review de seguridad
architect run "revisa src/auth/ en busca de vulnerabilidades: \
  inyección SQL, XSS, CSRF, gestión de secretos, \
  validación de inputs y principio de mínimo privilegio" \
  -a review --json > review-security.json

# Review de calidad general
architect run "revisa los últimos cambios en src/api/: \
  bugs, code smells, violaciones SOLID, \
  oportunidades de simplificación y tests faltantes" \
  -a review

# Review focalizada
architect run "revisa database.py: ¿hay connection leaks? \
  ¿se cierran todas las conexiones? ¿hay race conditions?" \
  -a review
```

### Generar documentación desde código

```bash
# Docstrings para un módulo
architect run "añade docstrings de tipo Google Style a todas las \
  funciones y clases de src/services/ que no tengan documentación" \
  --mode yolo

# README desde cero
architect run "genera un README.md completo para el proyecto: \
  descripción, instalación, uso, configuración, \
  estructura de directorios y ejemplos" \
  --mode yolo

# Documentar una API interna
architect run "lee todos los endpoints en src/api/routes/ \
  y genera un archivo docs/api-reference.md con la documentación \
  de cada endpoint: método, path, parámetros, respuestas y ejemplos" \
  --mode yolo
```

### Debugging asistido por IA

```bash
# Analizar un stack trace
architect run "este test falla con: 'TypeError: unhashable type: list' \
  en src/cache.py línea 45. Analiza el código, encuentra la causa \
  y corrige el bug" \
  --mode yolo --allow-commands

# Investigar un bug sin stack trace
architect run "los usuarios reportan que el login tarda >5s. \
  Analiza el flujo de autenticación, identifica cuellos de botella \
  y sugiere optimizaciones" \
  -a plan

# Fix + verificación automática
architect run "corrige el bug donde save_user() no valida \
  el campo 'role'. Después ejecuta pytest tests/test_user.py \
  para verificar que pasa" \
  --mode yolo --allow-commands
```

### Scaffolding de proyectos

```bash
# Estructura base
architect run "crea la estructura base para un servicio FastAPI: \
  main.py, routes/, models/, services/, tests/, Dockerfile, \
  requirements.txt y un README con instrucciones de desarrollo" \
  --mode yolo

# Añadir componente completo
architect run "añade un sistema CRUD completo para la entidad 'Product': \
  modelo Pydantic, endpoints REST (GET, POST, PUT, DELETE), \
  servicio con lógica de negocio, y tests para cada endpoint. \
  Sigue el patrón existente de la entidad 'User'" \
  --mode yolo --self-eval basic
```

---

## CI/CD y automatización

La clave para integrar architect en CI/CD es usar `--mode yolo` (sin confirmaciones interactivas), `--quiet --json` (salida parseable) y `--budget` (control de costes).

### Review automática en Pull Requests

**GitHub Actions:**

```yaml
name: AI Code Review
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  ai-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install architect
        run: pip install architect-ai-cli

      - name: AI Review
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          # Obtener archivos modificados
          FILES=$(git diff --name-only origin/${{ github.base_ref }}...HEAD | head -20)

          architect run \
            "Revisa estos archivos modificados en el PR: ${FILES}. \
             Busca bugs, problemas de seguridad, code smells y \
             oportunidades de mejora. Sé específico con archivo y línea." \
            -a review \
            --mode yolo \
            --quiet \
            --json \
            --budget 0.50 \
            > review.json

          # Publicar como comentario en el PR
          REVIEW=$(jq -r '.final_output' review.json)
          gh pr comment ${{ github.event.pull_request.number }} \
            --body "## AI Code Review\n\n${REVIEW}\n\n---\n_Generado por architect CLI_"
```

**GitLab CI:**

```yaml
ai-review:
  stage: review
  image: python:3.12-slim
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  before_script:
    - apt-get update && apt-get install -y git
    - pip install architect-ai-cli
  script:
    - |
      architect run \
        "revisa los cambios de este merge request y genera un informe de calidad" \
        -a review --mode yolo --quiet --json --budget 0.30 \
        > review.json
    - cat review.json | jq -r '.final_output'
  artifacts:
    paths:
      - review.json
    expire_in: 1 week
```

### Auditoría de seguridad en pipeline

```yaml
# GitHub Actions — Security audit semanal
name: Security Audit
on:
  schedule:
    - cron: '0 6 * * 1'  # Lunes 6:00 UTC
  workflow_dispatch:

jobs:
  security-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install architect
        run: pip install architect-ai-cli

      - name: Run security analysis
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run \
            "Realiza una auditoría de seguridad completa del proyecto: \
             1. Busca vulnerabilidades OWASP Top 10 \
             2. Verifica gestión de secretos (API keys en código, .env sin .gitignore) \
             3. Revisa validación de inputs en endpoints \
             4. Analiza dependencias con CVEs conocidos \
             5. Verifica configuraciones de CORS, CSP y headers de seguridad \
             Clasifica cada hallazgo como CRITICAL/HIGH/MEDIUM/LOW" \
            -a review \
            --mode yolo \
            --json \
            --budget 1.00 \
            > security-report.json

      - name: Check for critical findings
        run: |
          STATUS=$(jq -r '.status' security-report.json)
          OUTPUT=$(jq -r '.final_output' security-report.json)

          if echo "$OUTPUT" | grep -qi "CRITICAL"; then
            echo "::error::Se encontraron hallazgos CRITICAL"
            echo "$OUTPUT"
            exit 1
          fi

          echo "$OUTPUT"

      - name: Upload report
        uses: actions/upload-artifact@v4
        with:
          name: security-report
          path: security-report.json
```

### Generación de changelogs

```bash
# En un script de release
git log --oneline v1.0.0..HEAD > /tmp/commits.txt

architect run \
  "Lee /tmp/commits.txt con los commits desde la última release. \
   Genera un CHANGELOG.md con formato Keep a Changelog: \
   Added, Changed, Fixed, Removed. Agrupa por categoría \
   y redacta cada entrada de forma clara para el usuario final." \
  --mode yolo --quiet > CHANGELOG_DRAFT.md
```

### Autofix de linting en CI

```yaml
# GitHub Actions — Autofix y commit
name: Autofix
on:
  push:
    branches: [develop]

jobs:
  autofix:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GH_PAT }}

      - name: Install tools
        run: |
          pip install architect-ai-cli
          pip install ruff mypy

      - name: Autofix with architect
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run \
            "Ejecuta 'ruff check . --output-format json' y corrige \
             todos los errores de linting que encuentre. \
             Después ejecuta 'mypy src/' y corrige los errores de tipado. \
             No cambies lógica de negocio, solo correcciones de estilo y tipos." \
            --mode yolo \
            --allow-commands \
            --budget 0.50 \
            --self-eval basic

      - name: Commit fixes
        run: |
          git config user.name "architect-bot"
          git config user.email "architect@ci.local"
          git add -A
          git diff --staged --quiet || git commit -m "fix: autofix linting y tipos (architect)"
          git push
```

### Validación de migraciones

```bash
# Antes de aplicar una migración de base de datos
architect run \
  "Revisa la migración en migrations/0042_add_user_roles.py: \
   1. ¿Es reversible? \
   2. ¿Tiene impacto en rendimiento (locks largos, full table scans)? \
   3. ¿Mantiene backward compatibility con la versión actual del código? \
   4. ¿Los índices son correctos? \
   Recomienda si es safe para aplicar en producción sin downtime." \
  -a review --mode yolo --json
```

---

## QA y Calidad

### Generación de tests unitarios

```bash
# Tests para un módulo específico
architect run \
  "Genera tests unitarios para src/services/payment.py. \
   Cubre todos los flujos: éxito, errores de validación, \
   excepciones de red, y edge cases. Usa pytest y mocking. \
   Sigue el estilo de los tests existentes en tests/" \
  --mode yolo --self-eval basic

# Tests para código sin cobertura
architect run \
  "Ejecuta 'pytest --cov=src --cov-report=json' y analiza qué \
   funciones tienen 0% de cobertura. Genera tests para las 5 \
   funciones más críticas sin cobertura." \
  --mode yolo --allow-commands --budget 1.00
```

### Análisis de cobertura y tests faltantes

```bash
architect run \
  "Analiza los tests existentes en tests/ y compáralos con el código \
   en src/. Identifica: \
   1. Módulos sin ningún test \
   2. Funciones públicas sin test \
   3. Edge cases no cubiertos en tests existentes \
   4. Tests que prueban implementación en vez de comportamiento \
   Genera un informe priorizado." \
  -a review --mode yolo --json > test-gaps.json
```

### Quality gate con self-evaluation

El modo `--self-eval full` permite que el agente verifique su propio trabajo y corrija errores automáticamente.

```bash
# El agente implementa, verifica y corrige si falla
architect run \
  "Implementa una función calculate_tax(amount, region) en billing.py \
   que soporte las regiones US, EU y UK con sus respectivos impuestos. \
   Incluye tests en test_billing.py que cubran todos los escenarios." \
  --mode yolo \
  --self-eval full \
  --allow-commands \
  --budget 0.50

# Exit code 0 = la evaluación confirmó que la tarea se completó
# Exit code 2 = parcial, la evaluación detectó problemas
echo "Exit code: $?"
```

**Cómo funciona `--self-eval full`:**
1. El agente implementa la tarea normalmente.
2. Al terminar, un segundo prompt pregunta al LLM: "¿La tarea se completó correctamente?"
3. Si la confianza es < 80% (configurable), genera un prompt de corrección.
4. Re-ejecuta el agente con ese prompt de corrección.
5. Repite hasta `max_retries` (default: 2) o hasta que pase.

### Revisión de contratos de API

```bash
architect run \
  "Lee todos los schemas de la API en src/api/schemas/ y compáralos \
   con la documentación en docs/api.md. Identifica: \
   1. Campos documentados que no existen en el schema \
   2. Campos del schema no documentados \
   3. Tipos incorrectos en la documentación \
   4. Endpoints del código no documentados" \
  -a review --mode yolo --json
```

---

## DevOps

### Generación y revisión de IaC

```bash
# Generar Terraform desde descripción
architect run \
  "Genera un módulo Terraform para desplegar: \
   - VPC con 2 subnets públicas y 2 privadas \
   - ALB con target group y health checks \
   - ECS Fargate service con 2 tasks \
   - RDS PostgreSQL en subnet privada \
   Usa variables para región, nombre del proyecto y entorno." \
  --mode yolo

# Revisar IaC existente
architect run \
  "Revisa los archivos Terraform en infra/: \
   1. ¿Hay recursos sin tags? \
   2. ¿Se usan security groups demasiado permisivos (0.0.0.0/0)? \
   3. ¿Los secrets están hardcodeados? \
   4. ¿Falta encryption at rest en algún recurso? \
   5. ¿Se usan versiones fijas de providers?" \
  -a review --mode yolo
```

### Análisis de Dockerfiles y Helm charts

```bash
# Optimizar Dockerfile
architect run \
  "Analiza el Dockerfile y sugiere optimizaciones: \
   capas innecesarias, imagen base más ligera, multi-stage build, \
   seguridad (usuario non-root, COPY vs ADD), .dockerignore" \
  -a review

# Revisar Helm chart
architect run \
  "Revisa el Helm chart en helm/myapp/: \
   1. ¿Los values.yaml tienen defaults seguros? \
   2. ¿Se usan resource limits en todos los containers? \
   3. ¿Hay health checks (liveness/readiness probes)? \
   4. ¿Se montan secrets como env vars en lugar de files?" \
  -a review --mode yolo
```

### Revisión de configuraciones de seguridad

```bash
# Kubernetes RBAC
architect run \
  "Revisa los manifiestos de Kubernetes en k8s/: \
   1. ¿Algún ServiceAccount tiene permisos excesivos? \
   2. ¿Los Pods corren como root? \
   3. ¿Se usan NetworkPolicies? \
   4. ¿Los Secrets están cifrados o en texto plano?" \
  -a review --mode yolo --json > k8s-security.json
```

---

## Documentación técnica

### Documentación de APIs

```bash
# Generar docs desde código
architect run \
  "Lee todos los archivos en src/api/ y genera un archivo \
   docs/api-reference.md en formato Markdown con: \
   - Tabla de endpoints (método, path, descripción) \
   - Detalle de cada endpoint: parámetros, body, respuestas, errores \
   - Ejemplos de uso con curl \
   Usa el formato que ya existe en docs/ si hay alguno." \
  --mode yolo

# Mantener docs actualizadas
architect run \
  "Compara el código actual de src/api/ con docs/api-reference.md. \
   Actualiza la documentación para reflejar los cambios: \
   endpoints nuevos, parámetros cambiados, campos eliminados." \
  --mode yolo --self-eval basic
```

### Onboarding de nuevos desarrolladores

```bash
# Guía de arquitectura
architect run \
  "Genera un documento ARCHITECTURE.md que explique: \
   1. Visión general del sistema y qué problema resuelve \
   2. Diagrama de componentes (en ASCII/texto) \
   3. Flujo de datos principal (request → response) \
   4. Tecnologías y por qué se eligieron \
   5. Cómo añadir un nuevo endpoint (paso a paso) \
   6. Convenciones del proyecto (naming, estructura, tests)" \
  --mode yolo

# Glosario técnico
architect run \
  "Analiza el código y genera un GLOSSARY.md con todos los \
   términos de dominio del proyecto: entidades, servicios, \
   conceptos de negocio. Define cada uno con 1-2 frases." \
  --mode yolo
```

### Análisis de decisiones de arquitectura

```bash
# ADR (Architecture Decision Record)
architect run \
  "Analiza cómo está implementado el sistema de autenticación \
   (JWT, sesiones, OAuth, etc.). Genera un ADR (Architecture Decision \
   Record) que documente: contexto, decisión tomada, alternativas \
   consideradas, consecuencias y trade-offs." \
  -a plan --mode yolo --json | jq -r '.final_output' > docs/adr/001-auth.md
```

---

## Arquitecturas avanzadas con MCP

### Agente de desarrollo con múltiples MCP servers

Esta es la arquitectura más potente: architect conectado a servidores MCP que le dan acceso a GitHub, Jira, Slack y cualquier API que necesites.

```
┌──────────────────────────────────────────────────────────────┐
│                    Desarrollador                              │
│  architect run "implementa el ticket PROJ-123 y abre PR"     │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   architect (agente build)                     │
│                                                               │
│  Tools locales:        Tools MCP:                             │
│  ├─ read_file          ├─ jira_get_ticket    (Jira server)   │
│  ├─ edit_file          ├─ jira_add_comment   (Jira server)   │
│  ├─ write_file         ├─ gh_create_pr       (GitHub server) │
│  ├─ search_code        ├─ gh_create_branch   (GitHub server) │
│  ├─ run_command        ├─ slack_post_msg     (Slack server)  │
│  └─ ...                └─ db_query           (DB server)     │
└─────┬──────────┬──────────┬──────────┬──────────┬────────────┘
      │          │          │          │          │
      ▼          ▼          ▼          ▼          ▼
  Filesystem   MCP:Jira  MCP:GitHub MCP:Slack  MCP:DB
  (local)      :3001     :3002      :3003      :3004
```

**Configuración:**

```yaml
# config-full-agent.yaml

llm:
  model: claude-sonnet-4-6
  timeout: 120
  prompt_caching: true

mcp:
  servers:
    - name: jira
      url: http://localhost:3001
      token_env: JIRA_API_TOKEN

    - name: github
      url: http://localhost:3002
      token_env: GITHUB_TOKEN

    - name: slack
      url: http://localhost:3003
      token_env: SLACK_BOT_TOKEN

    - name: database
      url: http://localhost:3004
      token_env: DB_READ_TOKEN

workspace:
  root: /home/dev/projects/myapp

commands:
  enabled: true
  safe_commands:
    - "npm test"
    - "npm run lint"

hooks:
  post_edit:
    - name: eslint
      command: "npx eslint --fix {file}"
      file_patterns: ["*.ts", "*.tsx"]

costs:
  enabled: true
  budget_usd: 3.00
```

**Uso:**

```bash
# El agente lee el ticket de Jira, implementa el código,
# ejecuta tests, y abre un PR en GitHub
architect run \
  "Lee el ticket PROJ-123 de Jira. Implementa lo que pide. \
   Ejecuta los tests. Crea una rama feature/PROJ-123, \
   commitea los cambios y abre un PR en GitHub con la \
   descripción del ticket." \
  -c config-full-agent.yaml \
  --mode yolo \
  --show-costs

# El agente consulta la base de datos para entender el schema
# antes de implementar una feature
architect run \
  "Consulta la base de datos para ver el schema de la tabla 'users'. \
   Luego implementa un endpoint GET /users/search que permita \
   buscar usuarios por nombre o email con paginación." \
  -c config-full-agent.yaml \
  --mode yolo
```

### Architect como MCP server (implementador de código)

Architect puede funcionar como el "backend de implementación" de un agente orquestador más grande. Un agente de asistencia al desarrollo (por ejemplo un chatbot en Slack o un asistente de IDE) puede delegar la implementación de código a architect via un wrapper MCP.

```
┌─────────────────────────────────────────────────────────────┐
│           Agente Orquestador (IDE / Chatbot)                 │
│                                                              │
│  "El usuario quiere añadir autenticación al microservicio"   │
└──────────┬──────────┬──────────┬─────────────────────────────┘
           │          │          │
           ▼          ▼          ▼
    MCP: Git      MCP: Jira   MCP: Architect
    (branching)   (tickets)   (implementación)
                                    │
                                    ▼
                            ┌───────────────┐
                            │  architect run │
                            │  --mode yolo   │
                            │  --json        │
                            └───────────────┘
                                    │
                                    ▼
                             Código editado
                             Tests pasando
                             JSON con resultado
```

**Implementación del wrapper MCP para architect:**

```python
# mcp_architect_server.py — Ejemplo de servidor MCP que wrappea architect
import json
import subprocess

def handle_implement_code(params):
    """Tool MCP que ejecuta architect para implementar código."""
    prompt = params["prompt"]
    workspace = params.get("workspace", "/workspace")
    budget = params.get("budget", 1.0)

    result = subprocess.run(
        [
            "architect", "run", prompt,
            "--mode", "yolo",
            "--quiet", "--json",
            "-w", workspace,
            "--budget", str(budget),
        ],
        capture_output=True, text=True, timeout=300,
    )

    output = json.loads(result.stdout) if result.stdout else {}
    return {
        "status": output.get("status", "failed"),
        "output": output.get("final_output", ""),
        "exit_code": result.returncode,
        "costs": output.get("costs", {}),
    }
```

### Pipeline multi-agente

Encadena múltiples ejecuciones de architect con diferentes agentes para flujos complejos.

```bash
#!/bin/bash
# pipeline-feature.sh — Pipeline completo para implementar una feature

set -e
FEATURE="$1"
BUDGET_PER_STEP=0.50

echo "=== Paso 1: Planificación ==="
architect run \
  "Planifica cómo implementar: ${FEATURE}. \
   Lista los archivos a crear/modificar, los cambios \
   concretos y el orden de ejecución." \
  -a plan --mode yolo --quiet --json \
  --budget $BUDGET_PER_STEP \
  > /tmp/plan.json

PLAN=$(jq -r '.final_output' /tmp/plan.json)
echo "Plan generado."

echo "=== Paso 2: Implementación ==="
architect run \
  "Implementa el siguiente plan: ${PLAN}" \
  --mode yolo \
  --allow-commands \
  --budget $BUDGET_PER_STEP \
  --self-eval basic \
  --json > /tmp/impl.json

IMPL_STATUS=$(jq -r '.status' /tmp/impl.json)
echo "Implementación: ${IMPL_STATUS}"

echo "=== Paso 3: Review ==="
architect run \
  "Revisa los cambios realizados. Busca bugs, \
   problemas de seguridad y code smells. \
   Sé específico con archivo y línea." \
  -a review --mode yolo --quiet --json \
  --budget $BUDGET_PER_STEP \
  > /tmp/review.json

REVIEW=$(jq -r '.final_output' /tmp/review.json)
echo "Review completada."

echo "=== Paso 4: Correcciones (si hay problemas) ==="
if echo "$REVIEW" | grep -qi "bug\|critical\|security"; then
  architect run \
    "La review encontró estos problemas: ${REVIEW}. \
     Corrige los bugs y problemas de seguridad encontrados." \
    --mode yolo \
    --allow-commands \
    --budget $BUDGET_PER_STEP \
    --self-eval full

  echo "Correcciones aplicadas."
fi

echo "=== Pipeline completado ==="
# Coste total
TOTAL=$(jq -r '.costs.total_usd // 0' /tmp/plan.json /tmp/impl.json /tmp/review.json | \
  awk '{s+=$1} END {printf "%.4f", s}')
echo "Coste total: \$${TOTAL}"
```

### Integración con LiteLLM Proxy para equipos

Para equipos que quieren gestionar claves API, rate limits y costes centralizadamente.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│ Dev 1       │  │ Dev 2       │  │ CI/CD       │
│ architect   │  │ architect   │  │ architect   │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │   LiteLLM Proxy       │
            │   :8000               │
            │                       │
            │ - Rate limiting       │
            │ - Routing (GPT/Claude)│
            │ - Cost tracking       │
            │ - API key management  │
            │ - Caching             │
            │ - Logging             │
            └───────────┬───────────┘
                        │
              ┌─────────┼─────────┐
              │         │         │
              ▼         ▼         ▼
          OpenAI   Anthropic   Ollama
                               (local)
```

**Configuración:**

```yaml
# config-team.yaml
llm:
  mode: proxy
  model: gpt-4o
  api_base: http://litellm-proxy.internal:8000
  api_key_env: LITELLM_TEAM_KEY
  prompt_caching: true
```

```bash
# Cada desarrollador usa su team key
export LITELLM_TEAM_KEY="team-dev-key-..."
architect run "..." -c config-team.yaml --mode yolo
```

---

## AIOps y MLOps

### Revisión de pipelines de ML

```bash
# Revisar calidad de un pipeline de entrenamiento
architect run \
  "Revisa el pipeline de ML en ml/training/: \
   1. ¿Hay data leakage entre train y test? \
   2. ¿Se registran métricas y artifacts? \
   3. ¿El preprocesamiento es reproducible? \
   4. ¿Se versionan los datasets? \
   5. ¿Hay tests para las transformaciones de datos?" \
  -a review --mode yolo --json

# Revisar notebooks
architect run \
  "Analiza los notebooks en notebooks/: \
   ¿hay código duplicado que debería estar en módulos? \
   ¿hay celdas con outputs grandes que deberían limpiarse? \
   ¿hay imports no utilizados?" \
  -a review --mode yolo
```

### Generación de código de feature engineering

```bash
architect run \
  "En src/features/, crea funciones de feature engineering para: \
   1. Encoding de variables categóricas (one-hot, target encoding) \
   2. Normalización de variables numéricas (standard, minmax, robust) \
   3. Extracción de features de fechas (día semana, mes, quarter) \
   4. Handling de missing values (median, mode, KNN imputer) \
   Incluye tests con datos sintéticos. Usa scikit-learn y pandas." \
  --mode yolo --self-eval basic
```

### Análisis de drift en configuraciones

```bash
# Comparar configuraciones entre entornos
architect run \
  "Compara las configuraciones en config/production.yaml y \
   config/staging.yaml. Lista las diferencias: \
   valores que deberían ser iguales pero no lo son, \
   keys que existen en un entorno pero no en otro, \
   y valores que parecen incorrectos (URLs de producción en staging, etc.)" \
  -a plan --mode yolo --json
```

---

## Patrones de configuración

### Configuración para CI headless

```yaml
# config-ci.yaml — Sin interacción, máximo control
llm:
  model: gpt-4o-mini     # Más barato para CI
  timeout: 120
  stream: false           # Sin streaming en CI
  prompt_caching: true

logging:
  level: warn             # Solo errores en CI
  verbose: 0

evaluation:
  mode: basic             # Verificar que la tarea se completó
  confidence_threshold: 0.8

commands:
  enabled: true
  allowed_only: true      # Solo comandos safe/dev en CI

costs:
  enabled: true
  budget_usd: 1.00        # Límite duro por ejecución
  warn_at_usd: 0.50

indexer:
  enabled: true
  use_cache: false         # No cachear en CI efímero
```

```bash
architect run "..." -c config-ci.yaml --mode yolo --quiet --json
```

### Configuración para desarrollo local

```yaml
# config-dev.yaml — Interactivo, con feedback visual
llm:
  model: claude-sonnet-4-6
  timeout: 60
  stream: true            # Ver respuestas en tiempo real
  prompt_caching: true

logging:
  level: human            # Ver qué hace el agente
  verbose: 0

commands:
  enabled: true
  safe_commands:           # Tus scripts habituales
    - "make test"
    - "make lint"
    - "docker-compose up -d"

hooks:
  post_edit:
    - name: format
      command: "black {file}"
      file_patterns: ["*.py"]
    - name: lint
      command: "ruff check {file} --fix"
      file_patterns: ["*.py"]
    - name: typecheck
      command: "mypy {file} --ignore-missing-imports"
      file_patterns: ["*.py"]

costs:
  enabled: true
  budget_usd: 5.00
  warn_at_usd: 2.00

llm_cache:
  enabled: true           # Cache para desarrollo (ahorro de tokens)
  ttl_hours: 24
```

```bash
architect run "..." -c config-dev.yaml
# Con streaming visual, hooks automáticos, y cache activado
```

### Agentes custom por equipo

```yaml
# config-team.yaml
agents:
  # Agente de documentación (solo escribe docs, no toca código)
  documenter:
    system_prompt: |
      Eres un agente de documentación técnica.
      Solo generas y editas archivos .md en docs/.
      No modifiques código fuente ni tests.
    allowed_tools:
      - read_file
      - write_file
      - edit_file
      - list_files
      - search_code
      - grep
      - find_files
    confirm_mode: confirm-sensitive
    max_steps: 30

  # Agente de tests (solo escribe tests, no toca código de producción)
  tester:
    system_prompt: |
      Eres un agente de testing.
      Solo generas y editas archivos en tests/.
      Lee el código de producción para entender qué testear,
      pero nunca lo modifiques.
      Usa pytest, mocking y fixtures.
    allowed_tools:
      - read_file
      - write_file
      - edit_file
      - list_files
      - search_code
      - grep
      - find_files
      - run_command
    confirm_mode: yolo
    max_steps: 30

  # Agente de seguridad (solo lectura + informes)
  security:
    system_prompt: |
      Eres un experto en seguridad de aplicaciones.
      Analiza código en busca de vulnerabilidades OWASP Top 10,
      gestión de secretos, y configuraciones inseguras.
      Clasifica hallazgos como CRITICAL/HIGH/MEDIUM/LOW.
      Nunca modifiques archivos.
    allowed_tools:
      - read_file
      - list_files
      - search_code
      - grep
      - find_files
    confirm_mode: yolo
    max_steps: 25
```

```bash
architect run "documenta la API de usuarios" -a documenter -c config-team.yaml
architect run "genera tests para auth.py" -a tester -c config-team.yaml
architect run "auditoría de seguridad completa" -a security -c config-team.yaml --json
```

---

## Más casos de uso

### Guardrails para equipos

Protege el código base con reglas deterministas que el agente no puede ignorar.

```yaml
# config-team.yaml
guardrails:
  enabled: true
  protected_files:
    - ".env*"
    - "*.pem"
    - "deploy/**"
    - "Dockerfile"
    - "docker-compose*.yml"
  blocked_commands:
    - "git push"
    - "docker rm"
    - "kubectl delete"
  max_files_modified: 10
  max_lines_changed: 500
  require_test_after_edit: true
  code_rules:
    - pattern: "eval\\("
      message: "No usar eval() — riesgo de inyección de código"
      severity: block
    - pattern: "TODO|FIXME"
      message: "Marcador temporal detectado — resolver antes de merge"
      severity: warn
  quality_gates:
    - name: tests
      command: "pytest tests/ -x --tb=short"
      required: true
      timeout: 120
    - name: lint
      command: "ruff check src/"
      required: true
      timeout: 30
```

```bash
# El agente trabaja libremente pero dentro de los guardrails
architect run "refactoriza el módulo de pagos" \
  --mode yolo -c config-team.yaml
# → Si intenta editar .env → bloqueado
# → Si genera eval() → bloqueado
# → Al completar → pytest + ruff obligatorios
```

### Skills como marketplace interno

Crea skills reutilizables para tu equipo o comunidad.

```bash
# Crear skill local para patrones del proyecto
architect skill create django-patterns
# Editar .architect/skills/django-patterns/SKILL.md

# Compartir via GitHub
# Push .architect/skills/django-patterns/ al repo

# Otro dev instala la skill
architect skill install tu-org/repo/skills/django-patterns
```

**Ejemplo de SKILL.md para un framework:**

```markdown
---
name: fastapi-patterns
description: "Patrones FastAPI para este proyecto"
globs: ["**/routes/*.py", "**/schemas/*.py", "**/deps.py"]
---

# Patrones FastAPI

- Usar `Depends()` para inyección de dependencias
- Schemas de request/response en schemas/ con Pydantic v2
- Validación con `Field(...)`, nunca validación manual
- Excepciones con `HTTPException` y status codes correctos
- Endpoints async cuando usen I/O (db, http)
```

### Memoria procedural para proyectos largos

En proyectos donde interactúas con el agente durante días, la memoria reduce correcciones repetidas.

```yaml
memory:
  enabled: true
  auto_detect_corrections: true
```

```bash
# Sesión 1: el usuario corrige al agente
architect run "añade endpoint de login"
# → Agente genera código con npm
# → Usuario: "No, usa pnpm, no npm"
# → Corrección guardada en .architect/memory.md

# Sesión 2: el agente recuerda
architect run "añade endpoint de logout"
# → El system prompt incluye: "Correccion: No, usa pnpm, no npm"
# → Agente usa pnpm directamente
```

### Hooks de seguridad con pre-hooks

Bloquea acciones antes de que ocurran.

```bash
#!/bin/bash
# scripts/check-no-secrets.sh
# Pre-hook que bloquea si se detectan secretos en archivos escritos
if grep -qE "(sk-|AKIA|password\s*=\s*['\"])" "$ARCHITECT_FILE" 2>/dev/null; then
    echo "Archivo contiene posibles secretos" >&2
    exit 2   # BLOCK — el agente recibe "Bloqueado por hook"
fi
exit 0       # ALLOW
```

```yaml
hooks:
  pre_tool_use:
    - name: no-secrets
      command: "bash scripts/check-no-secrets.sh"
      matcher: "write_file|edit_file"
      file_patterns: ["*.py", "*.env", "*.yaml"]
      timeout: 5
```

---

## Sessions, Reports y Dry Run

### Tareas largas con budget incremental

Cuando una tarea es demasiado grande para un solo budget, usa sessions para continuar donde se quedó:

```bash
# Primera ejecución — se detiene por budget
architect run "refactoriza toda la capa de datos" --mode yolo --budget 1.00

# Ver sesiones
architect sessions
# 20260223-143022-a1b2   partial  15  $1.00   refactoriza toda la capa de datos

# Continuar (restaura contexto completo: mensajes, archivos, coste)
architect resume 20260223-143022-a1b2 --budget 2.00

# Si se interrumpe por Ctrl+C, la sesión también se guarda
# Continuar de nuevo
architect resume 20260223-143022-a1b2 --budget 1.00
```

### Reportes en Pull Requests

Genera reportes con secciones collapsible para GitHub:

```yaml
# .github/workflows/architect.yml
name: AI Review with Report
on:
  pull_request:
    types: [opened, synchronize]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install
        run: pip install architect-ai-cli

      - name: AI Review con reporte
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run "revisa los cambios del PR" \
            --mode yolo --quiet \
            --context-git-diff origin/${{ github.base_ref }} \
            --report github --report-file pr-report.md \
            --budget 1.00

      - name: Publicar reporte
        if: always()
        run: gh pr comment ${{ github.event.pull_request.number }} --body-file pr-report.md
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

El reporte incluye:
- Resumen: tarea, status, pasos, coste
- Archivos modificados (collapsible)
- Quality gates (si configurados)
- Timeline de pasos (collapsible)
- Git diff (collapsible)

### Reportes JSON para CI pipelines

```bash
# GitLab CI — reporte como artefacto
architect-audit:
  script:
    - architect run "auditoría de seguridad" \
        --mode yolo --report json --report-file report.json \
        --budget 0.50
    - |
      # Verificar resultado
      STATUS=$(jq -r '.status' report.json)
      FILES=$(jq '.files_modified | length' report.json)
      echo "Status: $STATUS, Archivos: $FILES"
  artifacts:
    paths: [report.json]
    expire_in: 1 week
```

### Dry Run para previsualizar cambios

Antes de ejecutar una tarea grande en producción, previsualiza qué haría el agente:

```bash
# Ver qué haría sin ejecutar nada
architect run "migra todos los tests de unittest a pytest" --dry-run

# El agente lee archivos normalmente, pero las escrituras se simulan
# Al final muestra un plan de acciones que ejecutaría:
# Plan de acciones (dry-run):
# 1. write_file → tests/test_auth.py
# 2. edit_file → tests/test_utils.py
# 3. run_command → pytest tests/ -x
# ...

# Si estás satisfecho con el plan, ejecutar de verdad
architect run "migra todos los tests de unittest a pytest" --mode yolo
```

### CI con resume automático

Pipeline que reintenta automáticamente si la ejecución queda parcial:

```bash
#!/bin/bash
# scripts/ci-with-retry.sh

architect run "$1" \
  --mode yolo --quiet --json \
  --budget 2.00 \
  --exit-code-on-partial \
  > result.json

EXIT=$?
if [ "$EXIT" -eq 2 ]; then
  echo "Parcial — intentando reanudar..."
  SESSION=$(jq -r '.session_id // empty' result.json)
  if [ -n "$SESSION" ]; then
    architect resume "$SESSION" --budget 1.00 --mode yolo --quiet --json > result2.json
  fi
fi
```

### Limpieza periódica de sesiones

En CI, las sesiones se acumulan. Agrega limpieza periódica:

```bash
# Cron job semanal
architect cleanup --older-than 7

# O en el pipeline de CI
architect cleanup --older-than 30
```

---

## Ralph Loop, Pipelines y Parallel

### Iteración automática hasta que los tests pasen

El Ralph Loop itera automáticamente hasta que un conjunto de checks pasan. Ideal para "fixear tests" o "implementar hasta que compile":

```bash
# Corregir tests rotos — el agente itera hasta que pasen
architect loop "corrige todos los tests que fallan en src/auth/" \
  --check "pytest tests/test_auth.py -x" \
  --max-iterations 10 \
  --max-cost 3.0

# Implementar y verificar calidad
architect loop "implementa validación de formularios en src/forms.py" \
  --check "pytest tests/" \
  --check "ruff check src/" \
  --check "mypy src/" \
  --max-iterations 15
```

Cada iteración usa un agente con **contexto limpio** — solo ve la tarea y los checks que fallaron. Esto evita degradación del contexto en tareas largas.

### Pipeline CI completo: implementar → testear → revisar

Define un workflow completo en YAML:

```yaml
# pipeline-feature.yaml
name: implement-test-review
variables:
  feature: "añadir endpoint de health check"

steps:
  - name: implement
    prompt: "Implementa: {{feature}}"
    agent: build
    checkpoint: true

  - name: test
    prompt: "Genera tests completos para los cambios del paso anterior"
    agent: build
    checks:
      - "pytest tests/ -x"
    checkpoint: true

  - name: lint
    prompt: "Corrige todos los errores de lint"
    agent: build
    condition: "ruff check src/ 2>&1 | grep -q 'error'"
    checks:
      - "ruff check src/"

  - name: review
    prompt: "Revisa los cambios realizados y genera un informe"
    agent: review
    output_var: review_result
```

```bash
# Ejecutar pipeline
architect pipeline pipeline-feature.yaml

# Reanudar desde el paso de tests (tras corrección manual)
architect pipeline pipeline-feature.yaml --from-step test

# Previsualizar sin ejecutar
architect pipeline pipeline-feature.yaml --dry-run
```

### Competición de modelos en paralelo

Ejecuta la misma tarea con diferentes modelos y compara resultados:

```bash
# Tres modelos compiten en worktrees aislados
architect parallel "optimiza las queries SQL del proyecto" \
  --models gpt-4o,claude-sonnet-4-6,deepseek-chat

# Inspeccionar resultados
cd .architect-parallel-1 && git diff HEAD~1  # resultado de gpt-4o
cd .architect-parallel-2 && git diff HEAD~1  # resultado de claude
cd .architect-parallel-3 && git diff HEAD~1  # resultado de deepseek

# Elegir el mejor y limpiar
architect parallel-cleanup
```

### Generación de tests en paralelo

Divide el trabajo de testing entre workers:

```bash
architect parallel \
  --task "genera tests para src/auth.py" \
  --task "genera tests para src/users.py" \
  --task "genera tests para src/billing.py" \
  --workers 3 \
  --budget-per-worker 1.0 \
  --timeout-per-worker 300

# Limpiar worktrees
architect parallel-cleanup
```

### CI/CD con Ralph Loop y reportes

```yaml
# .github/workflows/fix-and-report.yml
- name: Fix tests con Ralph Loop
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect loop "corrige los tests que fallan" \
      --check "pytest tests/ -x" \
      --max-iterations 5 \
      --max-cost 3.0

- name: Generar reporte
  run: |
    architect run "resume los cambios realizados" \
      -a resume --mode yolo \
      --report github --report-file pr-report.md

- name: Limpiar
  if: always()
  run: architect parallel-cleanup
```

### Auto-review en CI

Activa la revisión automática post-build para que un reviewer independiente inspeccione los cambios:

```yaml
# config-ci-review.yaml
auto_review:
  enabled: true
  review_model: claude-sonnet-4-6
  max_fix_passes: 1

# El flujo es automático:
# 1. Builder implementa → 2. Reviewer revisa (contexto limpio)
# → 3. Si hay issues, builder corrige → 4. Resultado final
```

```bash
architect run "implementa feature X" \
  --mode yolo --budget 3.0 \
  -c config-ci-review.yaml
```

---

## Evaluación, Health, Presets y Sub-Agentes (v1.0.0)

### Selección de modelo por tipo de tarea

Usa `architect eval` para determinar qué modelo es mejor para tu tipo de tarea:

```bash
# ¿Qué modelo es mejor para refactoring en tu codebase?
architect eval "refactoriza el módulo de auth usando dataclasses" \
  --models gpt-4o,claude-sonnet-4-6,deepseek-chat \
  --check "pytest tests/test_auth.py -q" \
  --check "ruff check src/auth/" \
  --budget-per-model 1.0 \
  --report-file eval_refactoring.md

# Compara resultados y elige el modelo que mejor rinda
```

### Monitoreo de calidad del código

Añade `--health` para medir el impacto de los cambios en la calidad:

```bash
# Refactorizar con medición de impacto
architect run "reduce la complejidad ciclomática de utils.py" \
  --health --mode yolo

# → Al finalizar:
# | Métrica            | Antes | Después | Delta |
# | Complejidad promedio | 8.2   | 4.1     | -4.1  |
# | Funciones largas   | 5     | 1       | -4    |
```

### Onboarding de equipos con presets

```bash
# Nuevo desarrollador se une al proyecto
architect init --preset python
# → .architect.md con convenciones del equipo
# → config.yaml con hooks de lint y quality gates

# Para proyectos con datos sensibles
architect init --preset paranoid
# → confirm-all, guardrails estrictos, code rules de seguridad
```

### Delegación de investigación a sub-agentes

El agente `build` puede delegar búsquedas y verificaciones a sub-agentes sin contaminar su contexto:

```bash
# En una tarea compleja, el agente principal puede:
# 1. Delegar exploración a un sub-agente "explore"
# 2. Implementar basándose en los resultados
# 3. Delegar verificación a un sub-agente "test"
# Todo esto ocurre automáticamente via dispatch_subagent

architect run "implementa una API REST para gestión de usuarios, \
  investigando primero los patrones existentes en el proyecto" \
  --mode yolo --budget 5.0
```

### Observabilidad con OpenTelemetry

Para equipos que quieren monitorear el uso del agente:

```yaml
# config.yaml
telemetry:
  enabled: true
  exporter: otlp
  endpoint: http://jaeger:4317
```

```bash
# Cada ejecución genera trazas con:
# - Duración total de la sesión
# - Tokens consumidos por llamada LLM
# - Coste acumulado
# - Tools ejecutadas con duración

architect run "implementa feature X" -c config.yaml --mode yolo
# → Traces visibles en Jaeger/Grafana
```

---

## Costes de referencia

Estimaciones basadas en uso real con modelos comunes. Los costes dependen del modelo, la complejidad de la tarea y el número de iteraciones.

| Caso de uso | Modelo | Tokens típicos | Coste estimado |
|-------------|--------|---------------|----------------|
| Review de código (1-5 archivos) | gpt-4o-mini | 5K–15K | $0.001–0.005 |
| Review de código (1-5 archivos) | gpt-4o | 5K–15K | $0.005–0.02 |
| Review de código (1-5 archivos) | claude-sonnet-4-6 | 5K–15K | $0.005–0.02 |
| Planificación de feature | gpt-4o | 10K–30K | $0.01–0.05 |
| Implementación simple (1-3 archivos) | gpt-4o | 15K–50K | $0.02–0.10 |
| Implementación con tests | gpt-4o | 30K–80K | $0.05–0.15 |
| Implementación + self-eval full | gpt-4o | 60K–150K | $0.10–0.30 |
| Refactorización multi-archivo | claude-sonnet-4-6 | 40K–100K | $0.05–0.20 |
| Resumen de proyecto | gpt-4o-mini | 3K–10K | $0.0005–0.003 |
| Auditoría de seguridad completa | gpt-4o | 20K–60K | $0.03–0.10 |

**Tips para optimizar costes:**
- Usa `gpt-4o-mini` para reviews y resúmenes (no necesitan capacidad de edición avanzada).
- Activa `prompt_caching: true` para reducir 50–90% en llamadas repetidas.
- Usa `--budget` para establecer límites duros.
- El agente `plan` es mucho más barato que `build` (solo lee, no itera con ediciones).
- Los hooks (ruff, mypy) añaden iteraciones: cada error detectado es una vuelta más al LLM.
- El cache local (`--cache`) elimina costes en re-ejecuciones idénticas durante desarrollo.
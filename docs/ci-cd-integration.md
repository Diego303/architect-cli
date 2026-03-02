# Integración CI/CD — Architect CLI v1.0.0

Guía completa para integrar `architect` en pipelines de CI/CD: GitHub Actions, GitLab CI, Jenkins y patrones avanzados. Todos los ejemplos son copy-pasteable y probados.

---

## Índice

- [Por qué architect en CI/CD](#por-qué-architect-en-cicd)
- [Principios de ejecución headless](#principios-de-ejecución-headless)
- [GitHub Actions](#github-actions)
- [GitLab CI](#gitlab-ci)
- [Bitbucket Pipelines](#bitbucket-pipelines)
- [Jenkins](#jenkins)
- [Patrones avanzados](#patrones-avanzados)
- [Parsing de salida JSON](#parsing-de-salida-json)
- [Gestión de secrets](#gestión-de-secrets)
- [Control de costes en CI](#control-de-costes-en-ci)
- [Checklist de integración](#checklist-de-integración)

---

## Por qué architect en CI/CD

Architect puede actuar como un agente autónomo dentro de pipelines de CI/CD para:

- **Revisar PRs automáticamente**: un agente `review` analiza el diff y publica un comentario con hallazgos.
- **Corregir código en push**: un agente `build` aplica fixes (lint, types, tests) y hace commit de las correcciones.
- **Generar código a partir de issues**: cuando se etiqueta un issue, un agente implementa la tarea y crea un PR.
- **Iterar hasta que los tests pasen**: el Ralph Loop ejecuta el agente en bucle hasta que `pytest` (u otros checks) den verde.
- **Comparar modelos**: evaluación competitiva de múltiples LLMs en la misma tarea con checks objetivos.

La clave es que architect está diseñado para ejecución headless desde su primer día: sin TTY, sin interacción, con salida JSON estructurada y exit codes semánticos.

---

## Principios de ejecución headless

### Modo yolo (obligatorio en CI)

En CI no hay terminal interactiva. El modo `--mode yolo` desactiva todas las confirmaciones. Sin él, architect detecta la ausencia de TTY y falla con `NoTTYError`.

```bash
architect run "tu tarea" --mode yolo
```

### Salida JSON estructurada

El flag `--json` emite un objeto JSON a stdout con toda la información de la ejecución:

```json
{
  "status": "success",
  "output": "Se han añadido 3 tests unitarios...",
  "steps": 8,
  "tools_used": ["read_file", "search_code", "write_file", "run_command"],
  "duration_seconds": 45.2,
  "costs": {
    "total_cost_usd": 0.0342
  },
  "session_id": "20260224-143022-a1b2c3"
}
```

Los valores posibles de `status` son: `success`, `partial`, `failed`.

### Exit codes semánticos

| Código | Significado | Acción en CI |
|--------|-------------|-------------|
| 0 | Tarea completada con éxito | Pipeline verde |
| 1 | Tarea fallida | Pipeline rojo |
| 2 | Tarea parcialmente completada | Pipeline amarillo (con `--exit-code-on-partial`) |
| 3 | Error de configuración | Revisar config/secrets |
| 4 | Error de autenticación (API key) | Verificar secrets del CI |
| 5 | Timeout | Aumentar timeout o budget |
| 130 | Interrumpido (SIGINT/SIGTERM) | Job cancelado |

### Flags esenciales para CI

```bash
architect run "PROMPT" \
  --mode yolo \              # Sin confirmaciones (headless)
  --json \                   # Salida JSON a stdout
  --quiet \                  # Mínimo ruido en stderr
  --budget 2.00 \            # Límite de gasto USD
  --show-costs \             # Resumen de costes al final
  --report FORMAT \          # json | markdown | github
  --report-file PATH \       # Guardar reporte en archivo (formato inferido de extensión si no se pasa --report)
  --context-git-diff REF \   # Inyectar diff como contexto
  --exit-code-on-partial \   # Exit 2 si status=partial
  --allow-commands \         # Permitir ejecución de comandos (pytest, etc.)
  --self-eval basic          # Auto-evaluación post-ejecución
```

### Idioma de salida (v1.1.0)

Los mensajes del sistema (logs HUMAN, reportes, guardrails) están en **inglés por defecto**. Si necesitas salida en español, configura la env var `ARCHITECT_LANGUAGE=es` o `language: es` en el YAML.

---

## GitHub Actions

### PR Review Bot

Revisa automáticamente cada PR y publica un comentario con el análisis.

```yaml
# .github/workflows/architect-review.yml
name: Architect PR Review

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Necesario para git diff

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install architect
        run: pip install architect-ai-cli

      - name: Run review agent
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run \
            "Revisa los cambios de este PR. Busca bugs, vulnerabilidades, \
             code smells y problemas de rendimiento. Sé conciso y accionable." \
            -a review \
            --mode yolo \
            --quiet \
            --context-git-diff origin/${{ github.base_ref }} \
            --report github \
            --report-file pr-review.md \
            --budget 1.00

      - name: Post review comment
        if: always() && hashFiles('pr-review.md') != ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr comment ${{ github.event.pull_request.number }} \
            --body-file pr-review.md
```

### Auto-fix on push

Ejecuta el agente para corregir problemas (lint, types, tests rotos) y hace commit de los fixes.

```yaml
# .github/workflows/architect-autofix.yml
name: Architect Auto-Fix

on:
  push:
    branches: [develop, "feature/**"]

permissions:
  contents: write

jobs:
  autofix:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.ARCHITECT_PAT }}  # PAT para poder pushear commits

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install architect and project deps
        run: |
          pip install architect-ai-cli
          pip install -e .[dev]

      - name: Run auto-fix agent
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run \
            "Ejecuta ruff check y mypy sobre el proyecto. Corrige todos \
             los errores que encuentres. NO cambies la lógica de negocio, \
             solo corrige errores de estilo, tipos y lint." \
            --mode yolo \
            --quiet \
            --json \
            --budget 1.50 \
            --allow-commands \
            --self-eval basic \
            > result.json

      - name: Commit fixes if any
        run: |
          STATUS=$(jq -r '.status' result.json)
          if [ "$STATUS" = "success" ] || [ "$STATUS" = "partial" ]; then
            git config user.name "architect-bot"
            git config user.email "architect-bot@users.noreply.github.com"
            git add -A
            git diff --cached --quiet || \
              git commit -m "fix: auto-fix lint/type errors via architect" && \
              git push
          fi
```

### Generación de código desde issues

Cuando se etiqueta un issue con `architect`, el agente implementa la tarea y crea un PR.

```yaml
# .github/workflows/architect-from-issue.yml
name: Architect Code Generation

on:
  issues:
    types: [labeled]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  generate:
    if: github.event.label.name == 'architect'
    runs-on: ubuntu-latest
    timeout-minutes: 20

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install architect and project deps
        run: |
          pip install architect-ai-cli
          pip install -e .[dev]

      - name: Create feature branch
        run: |
          BRANCH="architect/issue-${{ github.event.issue.number }}"
          git checkout -b "$BRANCH"
          echo "BRANCH=$BRANCH" >> "$GITHUB_ENV"

      - name: Run build agent
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect run \
            "${{ github.event.issue.title }}. ${{ github.event.issue.body }}" \
            --mode yolo \
            --json \
            --quiet \
            --budget 3.00 \
            --allow-commands \
            --self-eval basic \
            --report github \
            --report-file report.md \
            > result.json

      - name: Push and create PR
        if: success()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          git config user.name "architect-bot"
          git config user.email "architect-bot@users.noreply.github.com"
          git add -A
          git diff --cached --quiet && echo "Sin cambios" && exit 0
          git commit -m "feat: implement #${{ github.event.issue.number }} via architect"
          git push -u origin "$BRANCH"

          COST=$(jq -r '.costs.total_cost_usd // 0' result.json)

          gh pr create \
            --title "feat: #${{ github.event.issue.number }} — ${{ github.event.issue.title }}" \
            --body "$(cat <<EOF
          Implementación automática del issue #${{ github.event.issue.number }}.

          **Coste**: \$${COST} USD

          $(cat report.md)

          ---
          Generado por architect-cli
          EOF
          )" \
            --base main

      - name: Comment on issue
        if: always()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          STATUS=$(jq -r '.status // "unknown"' result.json 2>/dev/null || echo "error")
          COST=$(jq -r '.costs.total_cost_usd // 0' result.json 2>/dev/null || echo "N/A")

          gh issue comment ${{ github.event.issue.number }} --body \
            "Architect ha terminado. Status: **${STATUS}** | Coste: \$${COST} USD.
             Ver el workflow: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
```

### Ralph Loop en CI (iterar hasta que tests pasen)

```yaml
# .github/workflows/architect-ralph-loop.yml
name: Architect Ralph Loop

on:
  workflow_dispatch:
    inputs:
      task:
        description: "Tarea para el agente"
        required: true
      check_command:
        description: "Comando de verificación"
        required: true
        default: "pytest tests/ -q"
      max_iterations:
        description: "Máximo de iteraciones"
        required: false
        default: "5"

permissions:
  contents: write

jobs:
  ralph-loop:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install architect and project deps
        run: |
          pip install architect-ai-cli
          pip install -e .[dev]

      - name: Run Ralph Loop
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
        run: |
          architect loop "${{ github.event.inputs.task }}" \
            --check "${{ github.event.inputs.check_command }}" \
            --max-iterations ${{ github.event.inputs.max_iterations }} \
            --max-cost 5.00 \
            --quiet

      - name: Commit results
        if: success()
        run: |
          git config user.name "architect-bot"
          git config user.email "architect-bot@users.noreply.github.com"
          git add -A
          git diff --cached --quiet || \
            git commit -m "feat: ralph loop — ${{ github.event.inputs.task }}" && \
            git push
```

### Ejemplo completo con secrets, caching y artifacts

```yaml
# .github/workflows/architect-full.yml
name: Architect Full Pipeline

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  architect:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Cache pip
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-architect
          restore-keys: ${{ runner.os }}-pip-

      - name: Install architect
        run: pip install architect-ai-cli

      - name: Run review
        id: review
        env:
          LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
          ARCHITECT_MODEL: ${{ vars.ARCHITECT_MODEL || 'gpt-4o' }}
        run: |
          architect run \
            "Revisa exhaustivamente los cambios de este PR. Analiza: \
             1) Bugs y errores lógicos \
             2) Vulnerabilidades de seguridad \
             3) Problemas de rendimiento \
             4) Code smells y mantenibilidad \
             5) Cobertura de tests" \
            -a review \
            --mode yolo \
            --quiet \
            --json \
            --budget 2.00 \
            --show-costs \
            --context-git-diff origin/${{ github.base_ref }} \
            --report github \
            --report-file review-report.md \
            --exit-code-on-partial \
            > result.json

          echo "status=$(jq -r '.status' result.json)" >> "$GITHUB_OUTPUT"
          echo "cost=$(jq -r '.costs.total_cost_usd' result.json)" >> "$GITHUB_OUTPUT"

      - name: Post PR comment
        if: always() && hashFiles('review-report.md') != ''
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh pr comment ${{ github.event.pull_request.number }} \
            --body-file review-report.md

      - name: Upload artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: architect-results
          path: |
            result.json
            review-report.md
          retention-days: 30

      - name: Summary
        if: always()
        run: |
          echo "### Architect Review" >> "$GITHUB_STEP_SUMMARY"
          echo "" >> "$GITHUB_STEP_SUMMARY"
          echo "- **Status**: ${{ steps.review.outputs.status }}" >> "$GITHUB_STEP_SUMMARY"
          echo "- **Cost**: \$${{ steps.review.outputs.cost }} USD" >> "$GITHUB_STEP_SUMMARY"
```

---

## GitLab CI

### Pipeline completo: review + build + reporte

```yaml
# .gitlab-ci.yml
stages:
  - review
  - build
  - report

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  ARCHITECT_MODEL: "gpt-4o"

cache:
  paths:
    - .cache/pip/

# ── Stage: Review ─────────────────────────────────────────────────
architect-review:
  stage: review
  image: python:3.12-slim
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends git
    - pip install architect-ai-cli
  script:
    - |
      architect run \
        "Revisa los cambios de este MR. Busca bugs, vulnerabilidades y code smells." \
        -a review \
        --mode yolo \
        --quiet \
        --json \
        --budget 1.50 \
        --context-git-diff "origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}" \
        --report json \
        --report-file review-report.json \
        > result.json
  artifacts:
    paths:
      - result.json
      - review-report.json
    expire_in: 1 week
    reports:
      dotenv: architect.env
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

# ── Stage: Build + Tests ──────────────────────────────────────────
architect-build:
  stage: build
  image: python:3.12-slim
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends git
    - pip install architect-ai-cli
    - pip install -e .[dev]
  script:
    - |
      architect run \
        "Ejecuta pytest y corrige todos los tests rotos. \
         NO cambies la lógica de negocio, solo los tests." \
        --mode yolo \
        --quiet \
        --json \
        --budget 2.00 \
        --allow-commands \
        --self-eval basic \
        --report json \
        --report-file build-report.json \
        > build-result.json
    - |
      # Verificar resultado
      STATUS=$(jq -r '.status' build-result.json)
      echo "Architect status: $STATUS"
      if [ "$STATUS" = "failed" ]; then
        echo "Architect falló. Ver build-report.json para detalles."
        exit 1
      fi
  artifacts:
    paths:
      - build-result.json
      - build-report.json
    expire_in: 1 week
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

# ── Stage: Report ─────────────────────────────────────────────────
architect-report:
  stage: report
  image: python:3.12-slim
  dependencies:
    - architect-review
    - architect-build
  script:
    - |
      echo "=== Review Result ==="
      jq '.' review-report.json 2>/dev/null || echo "No review report"
      echo ""
      echo "=== Build Result ==="
      jq '.' build-report.json 2>/dev/null || echo "No build report"
      echo ""
      echo "=== Costes ==="
      REVIEW_COST=$(jq -r '.costs.total_cost_usd // 0' result.json 2>/dev/null || echo 0)
      BUILD_COST=$(jq -r '.costs.total_cost_usd // 0' build-result.json 2>/dev/null || echo 0)
      echo "Review: \$${REVIEW_COST} USD"
      echo "Build:  \$${BUILD_COST} USD"
  artifacts:
    paths:
      - review-report.json
      - build-report.json
    expire_in: 1 month
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
```

### Job standalone con Ralph Loop

```yaml
# Añadir al .gitlab-ci.yml existente
architect-ralph:
  stage: build
  image: python:3.12-slim
  before_script:
    - apt-get update && apt-get install -y --no-install-recommends git
    - pip install architect-ai-cli
    - pip install -e .[dev]
  script:
    - |
      architect loop "${ARCHITECT_TASK}" \
        --check "${ARCHITECT_CHECK:-pytest tests/ -q}" \
        --max-iterations ${ARCHITECT_MAX_ITER:-5} \
        --max-cost ${ARCHITECT_MAX_COST:-3.00} \
        --quiet
  rules:
    - if: '$ARCHITECT_TASK'
      when: manual
  timeout: 30m
```

Para ejecutar:

```bash
# Via GitLab API o UI
# Variables: ARCHITECT_TASK="implementa feature X", ARCHITECT_CHECK="pytest tests/", ARCHITECT_MAX_ITER=5
```

---

## Bitbucket Pipelines

### Pipeline completo: review + build

```yaml
# bitbucket-pipelines.yml
image: python:3.12-slim

definitions:
  caches:
    pip: ~/.cache/pip

  steps:
    - step: &architect-setup
        name: Setup
        script:
          - apt-get update && apt-get install -y --no-install-recommends git jq
          - pip install architect-ai-cli

pipelines:
  pull-requests:
    '**':
      - step:
          name: Architect PR Review
          caches:
            - pip
          script:
            - apt-get update && apt-get install -y --no-install-recommends git jq
            - pip install architect-ai-cli
            - |
              architect run \
                "Revisa los cambios de este PR. Busca bugs, vulnerabilidades, \
                 code smells y problemas de rendimiento. Sé conciso." \
                -a review \
                --mode yolo \
                --quiet \
                --json \
                --budget 1.50 \
                --context-git-diff "origin/${BITBUCKET_PR_DESTINATION_BRANCH}" \
                --report markdown \
                --report-file review.md \
                > result.json || true
            - |
              STATUS=$(jq -r '.status // "unknown"' result.json)
              COST=$(jq -r '.costs.total_cost_usd // 0' result.json)
              echo "Review status: ${STATUS} | Cost: \$${COST} USD"
          artifacts:
            - result.json
            - review.md

      - step:
          name: Architect Auto-Fix
          caches:
            - pip
          script:
            - apt-get update && apt-get install -y --no-install-recommends git jq
            - pip install architect-ai-cli
            - pip install -e .[dev] || true
            - |
              architect run \
                "Ejecuta ruff check y mypy. Corrige los errores encontrados. \
                 NO cambies la lógica de negocio, solo lint y tipos." \
                --mode yolo \
                --quiet \
                --json \
                --budget 2.00 \
                --allow-commands \
                --self-eval basic \
                > result.json
            - |
              STATUS=$(jq -r '.status' result.json)
              if [ "$STATUS" = "success" ] || [ "$STATUS" = "partial" ]; then
                git add -A
                git diff --cached --quiet || \
                  git commit -m "fix: auto-fix lint/type errors via architect" && \
                  git push
              fi
          artifacts:
            - result.json
```

### Review con comentario en PR via API

Bitbucket no tiene un CLI nativo como `gh`, pero puedes publicar comentarios en PRs usando la API REST:

```yaml
# bitbucket-pipelines.yml — step de review con comentario
- step:
    name: Review and Comment
    script:
      - apt-get update && apt-get install -y --no-install-recommends git jq curl
      - pip install architect-ai-cli
      - |
        architect run \
          "Revisa los cambios de este PR." \
          -a review \
          --mode yolo \
          --quiet \
          --context-git-diff "origin/${BITBUCKET_PR_DESTINATION_BRANCH}" \
          --report markdown \
          --report-file review.md \
          --budget 1.00 \
          > result.json || true
      - |
        # Publicar comentario en el PR via Bitbucket API
        if [ -f review.md ]; then
          REVIEW_CONTENT=$(cat review.md | jq -Rs .)
          curl -s -X POST \
            -H "Content-Type: application/json" \
            -u "${BITBUCKET_USER}:${BITBUCKET_APP_PASSWORD}" \
            "https://api.bitbucket.org/2.0/repositories/${BITBUCKET_REPO_FULL_NAME}/pullrequests/${BITBUCKET_PR_ID}/comments" \
            -d "{\"content\": {\"raw\": ${REVIEW_CONTENT}}}"
        fi
```

Variables requeridas como **Repository Variables** (Settings > Repository variables):

| Variable | Descripción | Secured |
|----------|-------------|---------|
| `LITELLM_API_KEY` | API key del proveedor LLM | Sí |
| `BITBUCKET_USER` | Usuario para API (o usar App Password) | No |
| `BITBUCKET_APP_PASSWORD` | App Password con permisos `pullrequest:write` | Sí |

**Variables automáticas de Bitbucket** (disponibles sin configuración):

| Variable | Ejemplo |
|----------|---------|
| `BITBUCKET_PR_DESTINATION_BRANCH` | `main` |
| `BITBUCKET_PR_ID` | `42` |
| `BITBUCKET_REPO_FULL_NAME` | `team/my-repo` |
| `BITBUCKET_BRANCH` | `feature/my-branch` |
| `BITBUCKET_COMMIT` | `a1b2c3d4` |

### Pipeline con Ralph Loop (trigger manual)

```yaml
# bitbucket-pipelines.yml
pipelines:
  custom:
    architect-ralph:
      - variables:
          - name: TASK
            default: "implementa feature X"
          - name: CHECK_CMD
            default: "pytest tests/ -q"
          - name: MAX_ITER
            default: "5"
      - step:
          name: Ralph Loop
          max-time: 30  # minutos
          caches:
            - pip
          script:
            - apt-get update && apt-get install -y --no-install-recommends git
            - pip install architect-ai-cli
            - pip install -e .[dev] || true
            - |
              architect loop "${TASK}" \
                --check "${CHECK_CMD}" \
                --max-iterations ${MAX_ITER} \
                --max-cost 5.00 \
                --quiet
            - |
              # Commit y push si hay cambios
              git add -A
              git diff --cached --quiet || \
                git commit -m "feat: ralph loop — ${TASK}" && \
                git push
```

Para ejecutar: Pipelines > Run pipeline > Custom: `architect-ralph` > Rellenar variables.

### Generación desde issue (via webhook + custom pipeline)

```yaml
# bitbucket-pipelines.yml
pipelines:
  custom:
    architect-from-issue:
      - variables:
          - name: ISSUE_TITLE
          - name: ISSUE_BODY
          - name: ISSUE_ID
      - step:
          name: Implement Issue
          max-time: 20
          script:
            - apt-get update && apt-get install -y --no-install-recommends git jq
            - pip install architect-ai-cli
            - pip install -e .[dev] || true
            - |
              BRANCH="architect/issue-${ISSUE_ID}"
              git checkout -b "$BRANCH"
            - |
              architect run \
                "${ISSUE_TITLE}. ${ISSUE_BODY}" \
                --mode yolo \
                --json \
                --quiet \
                --budget 3.00 \
                --allow-commands \
                --self-eval basic \
                > result.json
            - |
              STATUS=$(jq -r '.status' result.json)
              if [ "$STATUS" = "success" ] || [ "$STATUS" = "partial" ]; then
                git add -A
                git diff --cached --quiet && echo "Sin cambios" && exit 0
                git commit -m "feat: implement #${ISSUE_ID} via architect"
                git push -u origin "architect/issue-${ISSUE_ID}"

                # Crear PR via API
                curl -s -X POST \
                  -H "Content-Type: application/json" \
                  -u "${BITBUCKET_USER}:${BITBUCKET_APP_PASSWORD}" \
                  "https://api.bitbucket.org/2.0/repositories/${BITBUCKET_REPO_FULL_NAME}/pullrequests" \
                  -d "{
                    \"title\": \"feat: #${ISSUE_ID} — ${ISSUE_TITLE}\",
                    \"source\": {\"branch\": {\"name\": \"architect/issue-${ISSUE_ID}\"}},
                    \"destination\": {\"branch\": {\"name\": \"main\"}},
                    \"description\": \"Implementación automática del issue #${ISSUE_ID}.\\n\\nGenerado por architect-cli.\"
                  }"
              fi
          artifacts:
            - result.json
```

### Consideraciones específicas de Bitbucket

1. **Sin `gh` CLI**: Bitbucket no tiene CLI oficial como GitHub. Usa `curl` con la API REST v2.0 para crear PRs y comentarios.

2. **App Passwords**: Para operaciones autenticadas (push, crear PR, comentar), crea un App Password en Personal settings > App passwords con permisos:
   - `repository:write` — para push
   - `pullrequest:write` — para crear PRs y comentarios

3. **Límites de ejecución**: Bitbucket Pipelines tiene un límite de **120 minutos** por step y **500 minutos/mes** en el plan gratuito. Configura siempre `max-time` y `--budget` para controlar el consumo.

4. **Artifacts**: Los artifacts en Bitbucket se comparten entre steps del mismo pipeline. Usa `artifacts:` para pasar `result.json` entre steps.

5. **Variables secured**: Las variables marcadas como "Secured" en Bitbucket no se muestran en logs y no se exportan a forks. Usa siempre Secured para `LITELLM_API_KEY` y `BITBUCKET_APP_PASSWORD`.

6. **git push en pipelines**: Bitbucket Pipelines tienen un token de autenticación implícito para el repo. Si necesitas push, habilita "Pipelines > Settings > Enable push" o usa un App Password.

---

## Jenkins

### Pipeline declarativo completo

```groovy
// Jenkinsfile
pipeline {
    agent {
        docker {
            image 'python:3.12-slim'
            args '--network host'
        }
    }

    environment {
        LITELLM_API_KEY     = credentials('litellm-api-key')
        ARCHITECT_MODEL     = 'gpt-4o'
        PIP_CACHE_DIR       = "${WORKSPACE}/.cache/pip"
    }

    options {
        timeout(time: 20, unit: 'MINUTES')
        timestamps()
    }

    stages {
        stage('Setup') {
            steps {
                sh '''
                    apt-get update && apt-get install -y --no-install-recommends git jq
                    pip install architect-ai-cli
                    pip install -e .[dev] || true
                '''
            }
        }

        stage('Review') {
            when {
                changeRequest()
            }
            steps {
                sh '''
                    architect run \
                        "Revisa los cambios de este PR. Busca bugs y vulnerabilidades." \
                        -a review \
                        --mode yolo \
                        --quiet \
                        --json \
                        --budget 1.50 \
                        --context-git-diff origin/${CHANGE_TARGET} \
                        --report markdown \
                        --report-file review.md \
                        > review-result.json || true
                '''

                script {
                    def result = readJSON file: 'review-result.json'
                    echo "Review status: ${result.status}"
                    echo "Review cost: \$${result.costs?.total_cost_usd ?: 0} USD"
                }

                archiveArtifacts artifacts: 'review-result.json, review.md', allowEmptyArchive: true
            }
        }

        stage('Build & Fix') {
            steps {
                sh '''
                    architect run \
                        "Ejecuta los tests y corrige errores encontrados." \
                        --mode yolo \
                        --quiet \
                        --json \
                        --budget 2.00 \
                        --allow-commands \
                        --self-eval basic \
                        > build-result.json

                    STATUS=$(jq -r '.status' build-result.json)
                    echo "Build status: $STATUS"

                    if [ "$STATUS" = "failed" ]; then
                        echo "Architect reportó un fallo."
                        exit 1
                    fi
                '''

                archiveArtifacts artifacts: 'build-result.json', allowEmptyArchive: true
            }
        }

        stage('Cost Report') {
            steps {
                sh '''
                    echo "=== Resumen de costes ==="
                    for f in *-result.json; do
                        if [ -f "$f" ]; then
                            COST=$(jq -r '.costs.total_cost_usd // 0' "$f")
                            echo "$f: \$${COST} USD"
                        fi
                    done
                '''
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: '*.json, *.md', allowEmptyArchive: true
        }
        failure {
            echo 'El pipeline de architect falló. Revisar los artifacts para detalles.'
        }
    }
}
```

---

## Patrones avanzados

### Pipeline mode en CI (workflow YAML multi-step)

Define un workflow completo en YAML y ejecútalo en CI:

```yaml
# .architect/pipelines/feature-pipeline.yaml
name: feature-pipeline
variables:
  base_branch: origin/main
steps:
  - name: plan
    agent: plan
    prompt: |
      Analiza el proyecto y planifica cómo implementar: {{feature}}.
      Lista los archivos a crear/modificar y el orden de los cambios.
    output_var: plan

  - name: implement
    agent: build
    prompt: |
      Ejecuta este plan paso a paso:
      {{plan}}
    model: gpt-4o
    checks:
      - "pytest tests/ -q"
      - "ruff check src/"
    checkpoint: true

  - name: review
    agent: review
    prompt: "Revisa la implementación de {{feature}}. Sé crítico."
    output_var: review_notes

  - name: fix
    agent: build
    prompt: "Corrige estos problemas: {{review_notes}}"
    condition: "auto_fix == 'true'"
    checks:
      - "pytest tests/ -q"
    checkpoint: true
```

Ejecutar en CI:

```yaml
# GitHub Actions
- name: Run feature pipeline
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect pipeline .architect/pipelines/feature-pipeline.yaml \
      --var feature="autenticación JWT" \
      --var auto_fix=true
```

### Evaluación paralela (comparar modelos en CI)

Ejecuta la misma tarea con múltiples modelos y compara resultados:

```yaml
# GitHub Actions
- name: Eval — compare models
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect eval "Implementa un endpoint GET /health con test" \
      --models gpt-4o,claude-sonnet-4-6 \
      --check "pytest tests/test_health.py -q" \
      --budget-per-model 1.50

- name: Cleanup worktrees
  if: always()
  run: architect parallel-cleanup
```

Para ejecución paralela de tareas independientes:

```yaml
- name: Parallel tasks
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect parallel \
      --task "genera tests para src/auth.py" \
      --task "genera tests para src/users.py" \
      --task "genera tests para src/billing.py" \
      --workers 3 \
      --budget-per-worker 1.00 \
      --timeout-per-worker 300

- name: Cleanup
  if: always()
  run: architect parallel-cleanup
```

### Persistencia de sesiones entre CI runs

Resume trabajo interrumpido en un run posterior:

```yaml
# GitHub Actions — primer run
- name: Start implementation
  id: architect
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect run "refactoriza todo el módulo de auth" \
      --mode yolo \
      --json \
      --quiet \
      --budget 2.00 \
      > result.json

    echo "session_id=$(jq -r '.session_id // empty' result.json)" >> "$GITHUB_OUTPUT"
    echo "status=$(jq -r '.status' result.json)" >> "$GITHUB_OUTPUT"

- name: Save session
  if: steps.architect.outputs.status == 'partial'
  uses: actions/upload-artifact@v4
  with:
    name: architect-session
    path: .architect/sessions/
    retention-days: 7
```

```yaml
# GitHub Actions — segundo run (resume)
- name: Download session
  uses: actions/download-artifact@v4
  with:
    name: architect-session
    path: .architect/sessions/

- name: Resume implementation
  env:
    LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  run: |
    architect resume "${{ needs.previous.outputs.session_id }}" \
      --mode yolo \
      --json \
      --quiet \
      --budget 3.00 \
      > result.json
```

### Reporting de costes y alertas de budget

```yaml
# GitHub Actions — paso de verificación de costes
- name: Check cost threshold
  if: always()
  run: |
    COST=$(jq -r '.costs.total_cost_usd // 0' result.json)
    THRESHOLD=5.00

    echo "Coste: \$${COST} USD | Umbral: \$${THRESHOLD} USD"

    # Alerta si el coste supera el umbral
    if echo "$COST $THRESHOLD" | awk '{exit !($1 > $2)}'; then
      echo "::warning::El coste de architect (\$${COST}) superó el umbral de \$${THRESHOLD}"
    fi

    # Publicar en el summary
    echo "### Costes de Architect" >> "$GITHUB_STEP_SUMMARY"
    echo "| Métrica | Valor |" >> "$GITHUB_STEP_SUMMARY"
    echo "|---------|-------|" >> "$GITHUB_STEP_SUMMARY"
    echo "| Coste total | \$${COST} USD |" >> "$GITHUB_STEP_SUMMARY"
    echo "| Umbral | \$${THRESHOLD} USD |" >> "$GITHUB_STEP_SUMMARY"
```

### Uso de --context-git-diff para tareas PR-aware

El flag `--context-git-diff` inyecta el diff respecto a una referencia como contexto del agente. Esto permite que el agente trabaje solo sobre los cambios del PR.

```bash
# Review solo de los cambios del PR
architect run "revisa estos cambios" \
  -a review \
  --mode yolo \
  --context-git-diff origin/main

# Build que corrige solo los archivos modificados en el PR
architect run "corrige errores de lint en los archivos modificados" \
  --mode yolo \
  --context-git-diff origin/main \
  --allow-commands
```

En GitHub Actions, la referencia es típicamente `origin/${{ github.base_ref }}`. En GitLab CI, es `origin/${CI_MERGE_REQUEST_TARGET_BRANCH_NAME}`.

---

## Parsing de salida JSON

### Recetas con jq

```bash
# ── Extraer campos básicos ─────────────────────────────────────────

# Status de la ejecución
jq -r '.status' result.json

# Output del agente (texto libre)
jq -r '.output' result.json

# Coste total en USD
jq -r '.costs.total_cost_usd' result.json

# Session ID (para resume posterior)
jq -r '.session_id' result.json

# Número de pasos
jq -r '.steps' result.json

# Duración en segundos
jq -r '.duration_seconds' result.json

# ── Listas y arrays ───────────────────────────────────────────────

# Tools usadas (lista)
jq -r '.tools_used[]' result.json

# Tools usadas (separadas por coma)
jq -r '.tools_used | join(", ")' result.json

# Contar tools usadas
jq '.tools_used | length' result.json

# ── Análisis de reportes ───────────────────────────────────────────

# Archivos modificados (del reporte JSON)
jq -r '.files_modified[].path' report.json

# Solo archivos creados
jq -r '.files_modified[] | select(.action == "created") | .path' report.json

# Líneas añadidas totales
jq '[.files_modified[].lines_added] | add' report.json

# Quality gates que fallaron
jq '.quality_gates[] | select(.passed == false)' report.json

# ── Timeline y rendimiento ────────────────────────────────────────

# Tool más costosa
jq '.timeline | sort_by(.cost) | last' report.json

# Paso más lento
jq '.timeline | sort_by(.duration) | last' report.json

# Coste medio por paso
jq '.timeline | (map(.cost) | add) / length' report.json
```

### Patrones de error handling en bash

```bash
#!/bin/bash
# architect-ci.sh — Script robusto para CI

set -euo pipefail

RESULT_FILE="architect-result.json"

# Ejecutar architect (capturar exit code sin abortar por set -e)
EXIT_CODE=0
architect run "$TASK" \
  --mode yolo \
  --json \
  --quiet \
  --budget "${BUDGET:-2.00}" \
  > "$RESULT_FILE" || EXIT_CODE=$?

# Verificar que el archivo JSON es válido
if ! jq empty "$RESULT_FILE" 2>/dev/null; then
  echo "ERROR: architect no produjo JSON válido (exit code: $EXIT_CODE)"
  cat "$RESULT_FILE" >&2
  exit 1
fi

STATUS=$(jq -r '.status // "unknown"' "$RESULT_FILE")
COST=$(jq -r '.costs.total_cost_usd // 0' "$RESULT_FILE")
SESSION=$(jq -r '.session_id // empty' "$RESULT_FILE")

echo "Status: $STATUS | Cost: \$${COST} | Session: ${SESSION:-N/A}"

# Manejar cada exit code
case $EXIT_CODE in
  0)
    echo "Tarea completada con éxito."
    ;;
  1)
    echo "ERROR: La tarea falló."
    jq -r '.output' "$RESULT_FILE" >&2
    exit 1
    ;;
  2)
    echo "WARN: Tarea parcialmente completada."
    echo "Session ID para resume: $SESSION"
    # Opcionalmente: continuar o fallar
    ;;
  3)
    echo "ERROR: Problema de configuración."
    exit 3
    ;;
  4)
    echo "ERROR: API key inválida o expirada."
    exit 4
    ;;
  5)
    echo "ERROR: Timeout. Session: $SESSION"
    exit 5
    ;;
  130)
    echo "INFO: Ejecución interrumpida."
    exit 130
    ;;
  *)
    echo "ERROR: Exit code inesperado: $EXIT_CODE"
    exit "$EXIT_CODE"
    ;;
esac
```

---

## Gestión de secrets

### API keys como secrets de CI (nunca en config)

Architect utiliza variables de entorno para secrets. **Nunca** almacenes API keys en archivos de configuración YAML ni en el código fuente.

| Plataforma | Cómo configurar |
|------------|----------------|
| GitHub Actions | Settings > Secrets and variables > Actions > New repository secret |
| GitLab CI | Settings > CI/CD > Variables (masked + protected) |
| Jenkins | Credentials > Add > Secret text |

### LITELLM_API_KEY

La variable principal para el proveedor LLM:

```yaml
# GitHub Actions
env:
  LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}

# GitLab CI
variables:
  LITELLM_API_KEY: $LITELLM_API_KEY  # Configurada como variable CI/CD masked

# Jenkins
environment {
    LITELLM_API_KEY = credentials('litellm-api-key')
}
```

Si usas un LiteLLM Proxy compartido, la key del proxy es diferente de la key del proveedor directamente:

```yaml
env:
  LITELLM_API_KEY: ${{ secrets.LITELLM_PROXY_KEY }}
  ARCHITECT_API_BASE: "http://litellm-proxy.internal:8000"
```

### Tokens de servidores MCP

Si architect conecta con servidores MCP remotos (herramientas externas), sus tokens también deben ser secrets:

```yaml
# config.yaml — referencia por env var, nunca token directo
mcp:
  servers:
    - name: jira
      url: https://mcp-jira.internal/sse
      token_env: MCP_JIRA_TOKEN   # Resuelve desde $MCP_JIRA_TOKEN

    - name: github
      url: https://mcp-github.internal/sse
      token_env: MCP_GITHUB_TOKEN
```

```yaml
# GitHub Actions
env:
  LITELLM_API_KEY: ${{ secrets.LITELLM_API_KEY }}
  MCP_JIRA_TOKEN: ${{ secrets.MCP_JIRA_TOKEN }}
  MCP_GITHUB_TOKEN: ${{ secrets.MCP_GITHUB_TOKEN }}
```

### Checklist de secrets

- [ ] `LITELLM_API_KEY` como secret de CI (masked/protected)
- [ ] Tokens MCP via `token_env` (nunca `token` directo en YAML)
- [ ] `ARCHITECT_PAT` (Personal Access Token) si el bot necesita pushear commits
- [ ] Nunca incluir `.env`, `credentials.json` ni archivos con secrets en el workspace
- [ ] Verificar que los logs de CI no imprimen secrets (architect los sanitiza, pero otros pasos podrían no hacerlo)

---

## Control de costes en CI

### Budget por ejecución

Cada invocación debe tener un budget explícito. Sin él, no hay límite de gasto.

```bash
# Budget fijo por run
architect run "..." --mode yolo --budget 2.00

# Budget para Ralph Loop
architect loop "..." --check "pytest" --max-cost 5.00

# Budget por worker en parallel
architect parallel --task "..." --budget-per-worker 1.00
```

### Alertas de budget

Architect emite un warning cuando se acerca al límite. En config YAML:

```yaml
costs:
  enabled: true
  budget_usd: 2.00     # Límite hard (para la ejecución)
  warn_at_usd: 1.50    # Warning al alcanzar este umbral
```

Para alertas a nivel de CI:

```bash
# Verificar coste después de la ejecución
COST=$(jq -r '.costs.total_cost_usd // 0' result.json)
MAX_EXPECTED=3.00

if echo "$COST $MAX_EXPECTED" | awk '{exit !($1 > $2)}'; then
  echo "::warning::Coste elevado: \$${COST} USD (máximo esperado: \$${MAX_EXPECTED})"
fi
```

### Estrategias de selección de modelo

Usar modelos más baratos para tareas simples y reservar modelos caros para tareas complejas:

| Tarea | Modelo recomendado | Coste aproximado |
|-------|-------------------|------------------|
| Review de PR | `gpt-4o-mini`, `claude-haiku` | $0.01-0.05 por review |
| Lint/type fix | `gpt-4o-mini` | $0.02-0.10 por fix |
| Implementación compleja | `gpt-4o`, `claude-sonnet-4-6` | $0.10-0.50 por tarea |
| Generación de tests | `gpt-4o` | $0.05-0.30 por módulo |

```yaml
# GitHub Actions — modelo según el job
- name: Quick review (modelo barato)
  env:
    ARCHITECT_MODEL: gpt-4o-mini
  run: architect run "..." -a review --mode yolo --budget 0.50

- name: Full implementation (modelo capaz)
  env:
    ARCHITECT_MODEL: gpt-4o
  run: architect run "..." --mode yolo --budget 3.00
```

### Estrategias de caching

El cache LLM de architect almacena respuestas para evitar llamadas repetidas al proveedor:

```bash
# Activar cache (útil para retries del CI con el mismo prompt)
architect run "..." --mode yolo --cache

# Limpiar cache antes de ejecutar (forzar respuestas frescas)
architect run "..." --mode yolo --cache-clear
```

En CI, el cache es útil si el mismo job se re-ejecuta con el mismo prompt (retry). Para jobs diferentes, el cache no aporta valor ya que los prompts son distintos.

```yaml
# Persistir cache entre runs (GitHub Actions)
- name: Cache architect LLM
  uses: actions/cache@v4
  with:
    path: ~/.architect/cache
    key: architect-llm-${{ hashFiles('**/*.py') }}
    restore-keys: architect-llm-
```

### Monitorizar gasto mensual

Agrega los costes de todos los runs del mes:

```bash
#!/bin/bash
# monthly-cost-report.sh — ejecutar como cron job o scheduled workflow

TOTAL=0
for f in /path/to/ci-results/*.json; do
  COST=$(jq -r '.costs.total_cost_usd // 0' "$f" 2>/dev/null)
  TOTAL=$(echo "$TOTAL + $COST" | bc)
done

echo "Gasto mensual de architect: \$${TOTAL} USD"

MONTHLY_LIMIT=100.00
if echo "$TOTAL $MONTHLY_LIMIT" | awk '{exit !($1 > $2)}'; then
  echo "ALERTA: Gasto mensual (\$${TOTAL}) supera el límite de \$${MONTHLY_LIMIT}"
  # Enviar notificación (Slack, email, etc.)
fi
```

Workflow programado para GitHub Actions:

```yaml
# .github/workflows/cost-monitor.yml
name: Monthly Cost Monitor

on:
  schedule:
    - cron: '0 9 * * 1'  # Cada lunes a las 9:00

jobs:
  cost-report:
    runs-on: ubuntu-latest
    steps:
      - name: Download all architect artifacts
        uses: actions/download-artifact@v4
        with:
          pattern: architect-results-*
          merge-multiple: true

      - name: Calculate monthly cost
        run: |
          TOTAL=0
          for f in *.json; do
            COST=$(jq -r '.costs.total_cost_usd // 0' "$f" 2>/dev/null || echo 0)
            TOTAL=$(echo "$TOTAL + $COST" | bc)
          done

          echo "### Informe de costes semanal" >> "$GITHUB_STEP_SUMMARY"
          echo "Gasto total: \$${TOTAL} USD" >> "$GITHUB_STEP_SUMMARY"
```

---

## Checklist de integración

Guía paso a paso para configurar architect en un pipeline de CI nuevo.

### 1. Requisitos previos

- [ ] Python 3.12+ disponible en el runner (o usar imagen Docker `python:3.12-slim`)
- [ ] Git instalado en el runner
- [ ] API key del proveedor LLM (OpenAI, Anthropic, etc.) o acceso a LiteLLM Proxy
- [ ] Acceso de red saliente HTTPS al proveedor LLM desde el runner

### 2. Configurar secrets

- [ ] Crear secret `LITELLM_API_KEY` en la plataforma CI
- [ ] (Opcional) Crear secret `ARCHITECT_PAT` si el bot necesita pushear commits
- [ ] (Opcional) Crear secrets para tokens MCP (`MCP_*_TOKEN`)
- [ ] Verificar que los secrets estén masked en los logs

### 3. Instalar architect

- [ ] Añadir paso de instalación: `pip install architect-ai-cli`
- [ ] (Opcional) Instalar dependencias del proyecto: `pip install -e .[dev]`
- [ ] Verificar instalación: `architect --version`

### 4. Configurar el comando

- [ ] Definir el prompt específico para la tarea
- [ ] Seleccionar agente (`-a review`, `-a build`, `-a plan`)
- [ ] Añadir flags obligatorios: `--mode yolo --json --quiet`
- [ ] Configurar budget: `--budget N.NN`
- [ ] (Opcional) Añadir `--context-git-diff` para PRs
- [ ] (Opcional) Añadir `--report github` para comentarios de PR
- [ ] (Opcional) Añadir `--allow-commands` si el agente necesita ejecutar tests
- [ ] (Opcional) Añadir `--self-eval basic` para auto-verificación

### 5. Capturar y procesar resultados

- [ ] Redirigir stdout a archivo JSON: `> result.json`
- [ ] Verificar exit code con manejo explícito
- [ ] Parsear campos relevantes con `jq`
- [ ] (Opcional) Publicar comentario de PR con el reporte
- [ ] (Opcional) Subir artifacts (result.json, report)

### 6. Configurar protecciones

- [ ] Timeout del job (10-30 minutos según la tarea)
- [ ] Budget por ejecución (siempre explícito)
- [ ] `--exit-code-on-partial` si parcial debe ser failure
- [ ] Paso de limpieza (`if: always()`) para worktrees: `architect parallel-cleanup`

### 7. Probar y ajustar

- [ ] Ejecutar el pipeline manualmente con una tarea simple
- [ ] Verificar que los secrets se resuelven correctamente (exit code 4 = API key inválida)
- [ ] Verificar que el JSON de salida se parsea correctamente
- [ ] Ajustar budget y timeout según los costes reales observados
- [ ] (Opcional) Añadir cache de pip para acelerar la instalación

### 8. Monitorizar en producción

- [ ] Revisar costes semanalmente
- [ ] Configurar alertas si el gasto supera un umbral
- [ ] Revisar logs de ejecuciones fallidas (exit code 1 o 5)
- [ ] Actualizar architect periódicamente: `pip install --upgrade architect-ai-cli`

---

## Archivos relacionados

- **Contenedores**: [`containers.md`](containers.md) -- Dockerfiles, Kubernetes y OpenShift
- **Reportes**: [`reports.md`](reports.md) -- formatos JSON, Markdown y GitHub
- **Sesiones**: [`sessions.md`](sessions.md) -- persistencia y resume
- **Ralph Loop**: [`ralph-loop.md`](ralph-loop.md) -- iteración automática con checks
- **Parallel**: [`parallel.md`](parallel.md) -- ejecución paralela en worktrees
- **Pipelines**: [`pipelines.md`](pipelines.md) -- workflows YAML multi-step
- **Seguridad**: [`security.md`](security.md) -- modelo de seguridad completo
- **Dry Run**: [`dryrun.md`](dryrun.md) -- simulación de ejecución
- **Guía rápida**: [`fast-usage.md`](fast-usage.md) -- referencia de uso diario

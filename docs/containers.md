# Architect CLI en Contenedores

Guía completa para ejecutar `architect` en contenedores Docker, Kubernetes y Red Hat OpenShift.

## Índice

- [Requisitos del contenedor](#requisitos-del-contenedor)
- [Variables de entorno](#variables-de-entorno)
- [Directorios de trabajo](#directorios-de-trabajo)
- [Containerfile — Docker (root)](#containerfile--docker-root)
- [Containerfile — Docker (non-root)](#containerfile--docker-non-root)
- [Containerfile — Red Hat OpenShift (non-root, /tmp)](#containerfile--red-hat-openshift-non-root-tmp)
- [Ejemplo Docker: ejecución directa](#ejemplo-docker-ejecución-directa)
- [Ejemplo Kubernetes: Deployment](#ejemplo-kubernetes-deployment)
- [Ejemplo OpenShift: Deployment con SecurityContext](#ejemplo-openshift-deployment-con-securitycontext)
- [Configuración YAML para contenedores](#configuración-yaml-para-contenedores)
- [Patrones de uso](#patrones-de-uso)
- [Troubleshooting](#troubleshooting)

---

## Requisitos del contenedor

| Requisito | Detalle |
|-----------|---------|
| **Python** | 3.12+ |
| **Sistema** | Linux (glibc o musl) |
| **Git** | Necesario para clonar el repositorio e instalar architect, y para tools del agente |
| **Herramientas POSIX** | `ls`, `cat`, `find`, `grep`, `wc`, `head`, `tail` (incluidas en imágenes base) |
| **Red** | Acceso HTTPS saliente al proveedor LLM (OpenAI, Anthropic, etc.) |
| **Disco** | ~200 MB para imagen base + dependencias Python |

Architect **no** requiere:
- Acceso a TTY (en modo `yolo` no hay confirmaciones interactivas).
- Privilegios de root para su funcionamiento.
- Acceso a bases de datos o servicios externos (salvo la API del LLM y servidores MCP opcionales).

---

## Variables de entorno

### Requeridas

| Variable | Descripción |
|----------|-------------|
| `LITELLM_API_KEY` | API key del proveedor LLM. El nombre de esta variable se puede cambiar con `llm.api_key_env` en el YAML de configuración. |

### Opcionales (overrides)

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `ARCHITECT_MODEL` | Override del modelo LLM | `gpt-4o`, `claude-sonnet-4-6` |
| `ARCHITECT_API_BASE` | Override de la URL base de la API | `http://litellm-proxy:8000` |
| `ARCHITECT_LOG_LEVEL` | Override del nivel de logging | `debug`, `info`, `human`, `warn` |
| `ARCHITECT_WORKSPACE` | Override del workspace root | `/workspace` |
| `HOME` | Directorio home del usuario (afecta a `~/.architect/`) | `/tmp`, `/home/architect` |

### Para contenedores non-root (OpenShift)

| Variable | Valor recomendado | Motivo |
|----------|-------------------|--------|
| `HOME` | `/tmp` | Permite escribir en `~/.architect/` sin permisos especiales |

---

## Directorios de trabajo

Architect escribe en los siguientes directorios en tiempo de ejecución:

| Directorio | Propósito | Configurable |
|------------|-----------|--------------|
| `~/.architect/index_cache/` | Cache del índice del repositorio (TTL 5 min) | No directamente (depende de `HOME`) |
| `~/.architect/cache/` | Cache local de respuestas LLM (desarrollo) | Sí: `llm_cache.dir` |
| Workspace root | Directorio donde el agente lee/escribe archivos | Sí: `workspace.root`, `-w`, `ARCHITECT_WORKSPACE` |
| Log file | Archivo de logs JSON (opcional) | Sí: `logging.file`, `--log-file` |

**Todos estos directorios se crean automáticamente con fallo silencioso** — si el contenedor no tiene permisos de escritura en `~/.architect/`, el sistema funciona sin cache (solo pierde rendimiento en ejecuciones consecutivas).

En contenedores **non-root**, establece `HOME=/tmp` para que `~/.architect/` se resuelva a `/tmp/.architect/`, un directorio donde cualquier usuario puede escribir.

---

## Containerfile — Docker (root)

Imagen base para Docker ejecutando como root. La más sencilla para entornos locales y CI/CD.

```dockerfile
# ── Containerfile.root ─────────────────────────────────────────────
# Imagen Docker para architect CLI (root)
# Build: docker build -t architect:latest -f Containerfile.root .
# ───────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

LABEL maintainer="architect contributors"
LABEL description="architect CLI - Herramienta agentica headless para orquestar agentes de IA"

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clonar e instalar architect desde el repositorio
RUN git clone -b main --single-branch https://github.com/Diego303/architect-cli.git /opt/architect-cli && \
    cd /opt/architect-cli && \
    pip install --no-cache-dir -e .

# Directorio de trabajo por defecto (montaje del código fuente)
RUN mkdir -p /workspace
WORKDIR /workspace

# Crear directorios de cache
RUN mkdir -p /root/.architect/cache /root/.architect/index_cache

# Variables de entorno por defecto
ENV ARCHITECT_WORKSPACE=/workspace
ENV ARCHITECT_LOG_LEVEL=human

# Entrypoint
ENTRYPOINT ["architect"]
CMD ["--help"]
```

**Uso:**

```bash
# Build
docker build -t architect:latest -f Containerfile.root .

# Ejecución básica
docker run --rm \
  -e LITELLM_API_KEY="sk-..." \
  -v $(pwd):/workspace \
  architect:latest run "analiza este proyecto" --mode yolo

# Con configuración YAML custom
docker run --rm \
  -e LITELLM_API_KEY="sk-..." \
  -v $(pwd):/workspace \
  -v $(pwd)/config.yaml:/etc/architect/config.yaml:ro \
  architect:latest run "refactoriza main.py" \
    -c /etc/architect/config.yaml \
    --mode yolo
```

---

## Containerfile — Docker (non-root)

Imagen para Docker ejecutando como usuario sin privilegios. Recomendada para producción y CI/CD con requisitos de seguridad.

```dockerfile
# ── Containerfile.nonroot ──────────────────────────────────────────
# Imagen Docker para architect CLI (non-root)
# Build: docker build -t architect:nonroot -f Containerfile.nonroot .
# ───────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

LABEL maintainer="architect contributors"
LABEL description="architect CLI - non-root"

# Dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crear usuario sin privilegios
RUN groupadd --gid 1000 architect && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash architect

# Clonar e instalar architect (como root, antes de cambiar de usuario)
RUN git clone -b main --single-branch https://github.com/Diego303/architect-cli.git /opt/architect-cli && \
    cd /opt/architect-cli && \
    pip install --no-cache-dir -e .

# Crear directorios de trabajo con permisos correctos
RUN mkdir -p /workspace && chown architect:architect /workspace
RUN mkdir -p /home/architect/.architect/cache \
             /home/architect/.architect/index_cache && \
    chown -R architect:architect /home/architect/.architect

# Cambiar a usuario non-root
USER architect

WORKDIR /workspace

# Variables de entorno
ENV HOME=/home/architect
ENV ARCHITECT_WORKSPACE=/workspace
ENV ARCHITECT_LOG_LEVEL=human

ENTRYPOINT ["architect"]
CMD ["--help"]
```

**Uso:**

```bash
# Build
docker build -t architect:nonroot -f Containerfile.nonroot .

# Ejecución
docker run --rm \
  -e LITELLM_API_KEY="sk-..." \
  -v $(pwd):/workspace \
  architect:nonroot run "añade tests unitarios" --mode yolo
```

---

## Containerfile — Red Hat OpenShift (non-root, /tmp)

Red Hat OpenShift ejecuta los contenedores con un **UID arbitrario y aleatorio** asignado por el namespace, perteneciente al grupo `root` (GID 0). Esto implica:

- No se puede predecir el UID del usuario en build time.
- El directorio `HOME` del usuario no existe en el filesystem.
- Solo `/tmp` y directorios con permisos de grupo `root` son escribibles.

La solución es **redirigir `HOME` a `/tmp`** para que `~/.architect/` se resuelva a `/tmp/.architect/`. Architect crea automáticamente sus directorios de cache con `mkdir -p` y fallo silencioso, así que funciona en este escenario sin modificaciones de código.

```dockerfile
# ── Containerfile.openshift ────────────────────────────────────────
# Imagen para Red Hat OpenShift (non-root, UID arbitrario)
# Build: podman build -t architect:openshift -f Containerfile.openshift .
#
# OpenShift asigna un UID aleatorio en cada despliegue. Esta imagen
# usa HOME=/tmp para que architect pueda crear ~/.architect/ dentro
# de /tmp, que siempre es escribible.
# ───────────────────────────────────────────────────────────────────

FROM registry.access.redhat.com/ubi9/python-312:latest

LABEL maintainer="architect contributors"
LABEL description="architect CLI para OpenShift (non-root, UID arbitrario)"
LABEL io.openshift.tags="ai,agent,llm,cli"
LABEL io.k8s.description="Herramienta CLI agentica headless para orquestar agentes de IA"

# Como root para instalar dependencias
USER 0

# Instalar git (necesario para clonar el repo y para tools del agente)
RUN dnf install -y --nodocs git-core && \
    dnf clean all && \
    rm -rf /var/cache/dnf

# Clonar e instalar architect desde el repositorio
RUN git clone -b main --single-branch https://github.com/Diego303/architect-cli.git /opt/architect-cli && \
    cd /opt/architect-cli && \
    pip install --no-cache-dir -e .

# Crear workspace con permisos para GID 0 (grupo root en OpenShift)
RUN mkdir -p /workspace && \
    chgrp -R 0 /workspace && \
    chmod -R g=u /workspace

# Preparar /tmp para cache de architect (ya escribible, pero asegurar estructura)
# OpenShift garantiza que /tmp es escribible para cualquier UID
RUN mkdir -p /tmp/.architect/cache /tmp/.architect/index_cache && \
    chgrp -R 0 /tmp/.architect && \
    chmod -R g=u /tmp/.architect

# ── Configuración crítica para OpenShift ──────────────────────────
# HOME=/tmp → ~/.architect/ se resuelve a /tmp/.architect/
# Esto permite que architect cree caches sin permisos especiales.
# Es el mismo patrón que usan aider, pip y otras tools de Python
# cuando se ejecutan en contenedores con UID arbitrario.
ENV HOME=/tmp
ENV ARCHITECT_WORKSPACE=/workspace
ENV ARCHITECT_LOG_LEVEL=human

# Puerto (no necesario salvo para health checks HTTP custom)
# EXPOSE 8080

WORKDIR /workspace

# Cambiar a usuario non-root (OpenShift sobreescribirá el UID)
USER 1001

ENTRYPOINT ["architect"]
CMD ["--help"]
```

**Notas clave para OpenShift:**

1. **`HOME=/tmp`**: La variable más importante. Sin ella, `Path.home()` en Python falla o apunta a un directorio inexistente con UID arbitrario.

2. **`chgrp -R 0` + `chmod -R g=u`**: Patrón estándar de OpenShift. El UID aleatorio siempre pertenece al GID 0, así que dar permisos de grupo es equivalente a dar permisos al usuario.

3. **UBI 9 base**: Red Hat Universal Base Image 9 con Python 3.12. Soportada y certificada para OpenShift.

4. **Instalación via `git clone`**: Se clona el repositorio directamente en el contenedor y se instala en modo editable (`pip install -e .`), garantizando siempre la última versión de `main`.

---

## Ejemplo Docker: ejecución directa

### Caso básico — análisis de proyecto

```bash
docker run --rm \
  -e LITELLM_API_KEY="${LITELLM_API_KEY}" \
  -v "$(pwd):/workspace" \
  architect:latest run \
    "analiza la estructura del proyecto y genera un resumen" \
    --mode yolo \
    --quiet \
    --json
```

### Caso con modelo específico y budget

```bash
docker run --rm \
  -e LITELLM_API_KEY="${LITELLM_API_KEY}" \
  -e ARCHITECT_MODEL="claude-sonnet-4-6" \
  -v "$(pwd):/workspace" \
  architect:latest run \
    "refactoriza utils.py para usar dataclasses" \
    --mode yolo \
    --budget 0.50 \
    --show-costs
```

### Caso con LiteLLM Proxy (team/enterprise)

```bash
docker run --rm \
  -e LITELLM_API_KEY="team-key-..." \
  -e ARCHITECT_API_BASE="http://litellm-proxy:8000" \
  -v "$(pwd):/workspace" \
  architect:latest run \
    "genera documentación API para todos los endpoints" \
    --mode yolo
```

### Caso con config YAML y logs

```bash
docker run --rm \
  -e LITELLM_API_KEY="${LITELLM_API_KEY}" \
  -v "$(pwd):/workspace" \
  -v "$(pwd)/config.yaml:/etc/architect/config.yaml:ro" \
  -v "$(pwd)/logs:/var/log/architect" \
  architect:latest run \
    "añade validación de email a user.py" \
    -c /etc/architect/config.yaml \
    --log-file /var/log/architect/session.jsonl \
    --mode yolo
```

### Caso pipeline CI (salida JSON para parsear)

```bash
# En un step de CI (GitHub Actions, GitLab CI, Jenkins, etc.)
RESULT=$(docker run --rm \
  -e LITELLM_API_KEY="${LITELLM_API_KEY}" \
  -v "$(pwd):/workspace" \
  architect:latest run \
    "revisa el código y lista problemas de seguridad" \
    --mode yolo \
    --quiet \
    --json \
    -a review)

echo "${RESULT}" | jq '.final_output'
```

---

## Ejemplo Kubernetes: Deployment

### Deployment + ConfigMap + Secret

```yaml
# ── Secret: API key del LLM ───────────────────────────────────────
apiVersion: v1
kind: Secret
metadata:
  name: architect-llm-secret
  namespace: ai-tools
type: Opaque
stringData:
  LITELLM_API_KEY: "sk-tu-api-key-aqui"

---
# ── ConfigMap: configuración YAML de architect ─────────────────────
apiVersion: v1
kind: ConfigMap
metadata:
  name: architect-config
  namespace: ai-tools
data:
  config.yaml: |
    llm:
      model: gpt-4o
      timeout: 120
      stream: false
      prompt_caching: true

    workspace:
      root: /workspace

    logging:
      level: human
      file: /var/log/architect/session.jsonl

    indexer:
      enabled: true
      use_cache: true

    commands:
      enabled: true
      default_timeout: 60
      allowed_only: true

    evaluation:
      mode: basic

    costs:
      enabled: true
      budget_usd: 2.0
      warn_at_usd: 1.0

---
# ── Deployment ─────────────────────────────────────────────────────
apiVersion: apps/v1
kind: Deployment
metadata:
  name: architect-agent
  namespace: ai-tools
  labels:
    app: architect
spec:
  replicas: 1
  selector:
    matchLabels:
      app: architect
  template:
    metadata:
      labels:
        app: architect
    spec:
      # Security: non-root
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000

      containers:
        - name: architect
          image: architect:nonroot
          imagePullPolicy: IfNotPresent

          # Comando: se sobreescribe según la tarea
          command: ["architect"]
          args:
            - "run"
            - "analiza el proyecto y genera un informe de calidad"
            - "-c"
            - "/etc/architect/config.yaml"
            - "--mode"
            - "yolo"
            - "--quiet"
            - "--json"

          env:
            - name: LITELLM_API_KEY
              valueFrom:
                secretKeyRef:
                  name: architect-llm-secret
                  key: LITELLM_API_KEY
            - name: ARCHITECT_WORKSPACE
              value: "/workspace"
            - name: HOME
              value: "/home/architect"

          resources:
            requests:
              cpu: "100m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"

          volumeMounts:
            - name: workspace
              mountPath: /workspace
            - name: config
              mountPath: /etc/architect
              readOnly: true
            - name: logs
              mountPath: /var/log/architect
            - name: cache
              mountPath: /home/architect/.architect

          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop: ["ALL"]

      volumes:
        - name: workspace
          # Opción A: PVC con el código fuente
          persistentVolumeClaim:
            claimName: workspace-pvc
          # Opción B: EmptyDir para tareas efímeras
          # emptyDir: {}
        - name: config
          configMap:
            name: architect-config
        - name: logs
          emptyDir: {}
        - name: cache
          emptyDir: {}

      restartPolicy: Always
```

### Job (para tareas únicas)

Si architect se ejecuta como tarea puntual (CI, batch) en lugar de un servicio persistente, usa un **Job**:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: architect-review
  namespace: ai-tools
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        fsGroup: 1000

      containers:
        - name: architect
          image: architect:nonroot
          command: ["architect"]
          args:
            - "run"
            - "revisa el código y genera un informe de seguridad"
            - "--mode"
            - "yolo"
            - "--quiet"
            - "--json"
            - "-a"
            - "review"
            - "--budget"
            - "1.0"

          env:
            - name: LITELLM_API_KEY
              valueFrom:
                secretKeyRef:
                  name: architect-llm-secret
                  key: LITELLM_API_KEY
            - name: ARCHITECT_WORKSPACE
              value: "/workspace"
            - name: HOME
              value: "/home/architect"

          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "1"
              memory: "512Mi"

          volumeMounts:
            - name: workspace
              mountPath: /workspace

      volumes:
        - name: workspace
          persistentVolumeClaim:
            claimName: workspace-pvc

      restartPolicy: Never
```

---

## Ejemplo OpenShift: Deployment con SecurityContext

OpenShift aplica **Security Context Constraints (SCC)** más estrictas que Kubernetes vanilla. La SCC `restricted-v2` (default) impone:

- UID aleatorio (no se puede elegir `runAsUser`).
- No `allowPrivilegeEscalation`.
- Solo capabilities `NET_BIND_SERVICE` (si hace falta).
- `readOnlyRootFilesystem` opcional pero recomendado.

```yaml
# ── Secret: API key ────────────────────────────────────────────────
apiVersion: v1
kind: Secret
metadata:
  name: architect-llm-secret
  namespace: ai-agents
type: Opaque
stringData:
  LITELLM_API_KEY: "sk-tu-api-key-aqui"

---
# ── ConfigMap: configuración para OpenShift ────────────────────────
apiVersion: v1
kind: ConfigMap
metadata:
  name: architect-config
  namespace: ai-agents
data:
  config.yaml: |
    llm:
      model: gpt-4o
      timeout: 120
      stream: false
      prompt_caching: true

    workspace:
      root: /workspace

    logging:
      level: human
      # Logs en /tmp (escribible en OpenShift)
      file: /tmp/architect-logs/session.jsonl

    indexer:
      enabled: true
      use_cache: true

    # Cache en /tmp (HOME=/tmp → ~/.architect/ = /tmp/.architect/)
    llm_cache:
      enabled: false
      dir: /tmp/.architect/cache

    commands:
      enabled: true
      default_timeout: 60
      allowed_only: true

    evaluation:
      mode: basic

    costs:
      enabled: true
      budget_usd: 2.0

---
# ── DeploymentConfig / Deployment ──────────────────────────────────
apiVersion: apps/v1
kind: Deployment
metadata:
  name: architect-agent
  namespace: ai-agents
  labels:
    app: architect
    app.kubernetes.io/name: architect
    app.kubernetes.io/component: agent
spec:
  replicas: 1
  selector:
    matchLabels:
      app: architect
  template:
    metadata:
      labels:
        app: architect
    spec:
      # OpenShift SCC restricted-v2: no especificar runAsUser (será aleatorio)
      securityContext:
        runAsNonRoot: true
        # No especificar runAsUser — OpenShift asigna UID aleatorio
        # El UID siempre pertenece a GID 0 (root group)

      containers:
        - name: architect
          image: image-registry.openshift-image-registry.svc:5000/ai-agents/architect:openshift
          imagePullPolicy: Always

          command: ["architect"]
          args:
            - "run"
            - "analiza el proyecto y genera un informe de calidad"
            - "-c"
            - "/etc/architect/config.yaml"
            - "--mode"
            - "yolo"
            - "--quiet"
            - "--json"

          env:
            # API key desde Secret
            - name: LITELLM_API_KEY
              valueFrom:
                secretKeyRef:
                  name: architect-llm-secret
                  key: LITELLM_API_KEY

            # ── CRÍTICO: HOME=/tmp ──
            # Sin esto, Path.home() falla con UID arbitrario.
            # ~/.architect/ se resuelve a /tmp/.architect/
            - name: HOME
              value: "/tmp"

            - name: ARCHITECT_WORKSPACE
              value: "/workspace"

            # Opcional: override de modelo via env var
            # - name: ARCHITECT_MODEL
            #   value: "claude-sonnet-4-6"

          resources:
            requests:
              cpu: "100m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"

          volumeMounts:
            - name: workspace
              mountPath: /workspace
            - name: config
              mountPath: /etc/architect
              readOnly: true
            # /tmp ya es escribible — no necesita volumen extra
            # pero puedes montar emptyDir si quieres persistir logs entre reinicios
            - name: tmp-data
              mountPath: /tmp

          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            # readOnlyRootFilesystem: true  # Descomentar si la SCC lo requiere
            # Si activamos readOnly, /tmp debe ser un volumen montado

      volumes:
        - name: workspace
          persistentVolumeClaim:
            claimName: workspace-pvc
        - name: config
          configMap:
            name: architect-config
        - name: tmp-data
          emptyDir:
            sizeLimit: 500Mi

      restartPolicy: Always
```

### Buildconfig para OpenShift (build interno)

Si prefieres que OpenShift construya la imagen desde el repositorio:

```yaml
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: architect-build
  namespace: ai-agents
spec:
  source:
    type: Git
    git:
      uri: "https://github.com/Diego303/architect-cli.git"
      ref: main
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Containerfile.openshift
  output:
    to:
      kind: ImageStreamTag
      name: "architect:openshift"
  triggers:
    - type: ConfigChange
```

---

## Configuración YAML para contenedores

Ejemplo de `config.yaml` optimizado para ejecución en contenedores:

```yaml
# config-container.yaml — Configuración optimizada para contenedores
# Montar como ConfigMap en /etc/architect/config.yaml

llm:
  model: gpt-4o
  timeout: 120
  retries: 3
  # Streaming deshabilitado en contenedores (no hay terminal interactivo)
  stream: false
  # Prompt caching recomendado para reducir costes en ejecuciones repetidas
  prompt_caching: true

workspace:
  root: /workspace
  allow_delete: false

logging:
  level: human
  verbose: 0
  # Logs en directorio escribible (ajustar según entorno)
  # Docker/K8s: /var/log/architect/
  # OpenShift:  /tmp/architect-logs/
  # file: /var/log/architect/session.jsonl

indexer:
  enabled: true
  use_cache: true

context:
  max_tool_result_tokens: 2000
  summarize_after_steps: 8
  max_context_tokens: 80000
  parallel_tools: true

evaluation:
  # basic recomendado para CI — verifica que la tarea se completó
  mode: basic
  confidence_threshold: 0.8

commands:
  enabled: true
  default_timeout: 60
  max_output_lines: 200
  # En CI/producción: solo comandos seguros y de desarrollo
  allowed_only: true

costs:
  enabled: true
  # Budget por ejecución (ajustar según tarea)
  budget_usd: 2.0
  warn_at_usd: 1.0

llm_cache:
  # Deshabilitado por defecto en contenedores efímeros
  enabled: false
  dir: ~/.architect/cache
  ttl_hours: 24

hooks:
  post_edit: []
```

---

## Patrones de uso

### 1. Tarea one-shot (Job / docker run)

El patrón más común: ejecutar una tarea y obtener el resultado.

```bash
# Docker
docker run --rm \
  -e LITELLM_API_KEY="$KEY" \
  -v ./src:/workspace \
  architect:latest run "añade docstrings a todos los módulos" \
    --mode yolo --quiet --json

# Kubernetes Job (ver ejemplo arriba)
kubectl apply -f job-architect.yaml
kubectl logs job/architect-review
```

### 2. Agente en pipeline CI/CD

```yaml
# GitHub Actions
- name: Code Review con Architect
  run: |
    docker run --rm \
      -e LITELLM_API_KEY="${{ secrets.LITELLM_API_KEY }}" \
      -v ${{ github.workspace }}:/workspace \
      architect:nonroot run \
        "revisa los cambios del último commit y genera un informe" \
        -a review --mode yolo --quiet --json \
      > review.json

    # Parsear resultado
    cat review.json | jq -r '.final_output'
```

### 3. Agente con LiteLLM Proxy (equipo)

Cuando hay un proxy LiteLLM compartido para gestionar claves y rate limits:

```bash
docker run --rm \
  -e LITELLM_API_KEY="team-key" \
  -e ARCHITECT_API_BASE="http://litellm-proxy.internal:8000" \
  -v ./:/workspace \
  architect:latest run "optimiza las queries SQL" --mode yolo
```

### 4. Agente con modelo local (Ollama)

Para ejecución completamente local sin acceso a internet:

```bash
# Ollama corriendo en el host o en otro contenedor
docker run --rm \
  --network host \
  -e ARCHITECT_MODEL="ollama/llama3" \
  -e ARCHITECT_API_BASE="http://localhost:11434" \
  -e LITELLM_API_KEY="dummy" \
  -v ./:/workspace \
  architect:latest run "explica la arquitectura del proyecto" \
    --mode yolo -a review
```

### 5. Múltiples agentes en paralelo

```bash
# Lanzar análisis y review en paralelo
docker run --rm -d --name architect-review \
  -e LITELLM_API_KEY="$KEY" \
  -v ./:/workspace:ro \
  architect:latest run "review de seguridad" -a review --mode yolo --json

docker run --rm -d --name architect-docs \
  -e LITELLM_API_KEY="$KEY" \
  -v ./:/workspace \
  architect:latest run "genera README.md" --mode yolo

# Esperar resultados
docker wait architect-review architect-docs
docker logs architect-review > review.json
docker logs architect-docs
```

---

## Troubleshooting

### `Path.home()` falla con UID arbitrario (OpenShift)

```
RuntimeError: Could not determine home directory
```

**Solución**: Establecer `HOME=/tmp` en las variables de entorno del contenedor.

```yaml
env:
  - name: HOME
    value: "/tmp"
```

### Permisos denegados al escribir cache

```
[warning] llm_cache.dir_create_failed path=/home/nonexistent/.architect/cache
```

**Solución**: Es un warning no bloqueante — architect funciona sin cache. Para eliminarlo, asegura que `HOME` apunte a un directorio escribible o configura `llm_cache.dir` a un path escribible.

### Timeout al conectar con el LLM

```
Error: Timeout: Connection timed out
```

**Solución**:
- Verificar que el contenedor tiene acceso de red al proveedor LLM.
- En OpenShift, verificar las NetworkPolicies del namespace.
- Si usas proxy, verificar `ARCHITECT_API_BASE`.
- Aumentar el timeout: `--timeout 300` o `llm.timeout: 300` en config.

### El contenedor se queda colgado sin salir

Si el agente no termina, puede ser porque está esperando confirmación interactiva.

**Solución**: Usar siempre `--mode yolo` en contenedores. Sin terminal, los modos `confirm-all` y `confirm-sensitive` bloquean la ejecución.

### Exit codes

| Código | Significado |
|--------|-------------|
| 0 | Tarea completada con éxito |
| 1 | Tarea fallida |
| 2 | Tarea parcialmente completada |
| 3 | Error de configuración |
| 4 | Error de autenticación (API key inválida) |
| 5 | Timeout |
| 130 | Interrumpido (SIGINT/SIGTERM) |

Usa el exit code en pipelines CI/CD para determinar si el paso fue exitoso:

```bash
docker run --rm ... architect:latest run "..." --mode yolo
EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
  echo "Architect falló con código: $EXIT_CODE"
  exit 1
fi
```

### El workspace está vacío dentro del contenedor

Verificar que el volumen se monta correctamente:

```bash
# Verificar que el path del host existe
ls -la $(pwd)

# Ejecutar con debug para ver el workspace
docker run --rm \
  -e LITELLM_API_KEY="$KEY" \
  -v "$(pwd):/workspace" \
  architect:latest run "lista los archivos" --mode yolo -v
```

En Kubernetes, verificar que el PVC está bound y el pod lo monta:

```bash
kubectl describe pod architect-agent-xxx | grep -A5 Volumes
kubectl exec architect-agent-xxx -- ls -la /workspace
```

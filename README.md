# 🏗️ architect

**architect** es una herramienta CLI **headless y agentica** para **diseñar, planificar y ejecutar tareas complejas** usando modelos de lenguaje, con **control explícito**, **configuración declarativa** y **sin intervención humana innecesaria**.

Piensa como un arquitecto.
Actúa como un operador.
Ejecuta sin manos.

---

## ✨ ¿Qué es architect?

`architect` es un **motor de agentes de IA por terminal**, diseñado para:

* funcionar en **entornos no interactivos** (CI, cron, pipelines)
* ejecutar tareas reales sobre el sistema de archivos
* usar LLMs de forma **controlada y auditable**
* permitir **planificación antes de ejecución**
* escalar desde análisis hasta automatización total (`yolo`)

No es un chatbot.
No es una TUI.
Es una **herramienta de ejecución**.

---

## 🧠 Filosofía

* **Headless first**
  Todo debe funcionar sin UI, sin TTY y sin suposiciones humanas.

* **El LLM no manda**
  El modelo propone, `architect` decide y ejecuta.

* **Diseño antes que acción**
  Plan → validación → ejecución.

* **Configuración declarativa**
  Un YAML define el mundo. La CLI solo lo ajusta.

* **Menos magia, más control**
  Cada acción pasa por políticas claras.

---

## 🚀 Qué puede hacer

* 🧩 Ejecutar tareas mediante **agentes de IA** (`plan`, `build`, `resume`, etc.)
* 📁 Leer, crear, modificar y borrar archivos
* 🔌 Usar **herramientas externas vía MCP** (HTTP, streaming, token)
* 🧠 Soportar **múltiples agentes/modos**, configurables por YAML
* 🛡️ Controlar acciones con **modos de confirmación**
* 📜 Registrar todo con **logs estructurados + salida legible**
* ⚙️ Integrarse fácilmente en **scripts, CI y pipelines**

---

## 🧑‍💻 Ejemplo rápido

```bash
architect plan "analiza este proyecto y propone una refactorización"
```

```bash
architect run --agent build "aplica el plan y modifica los archivos necesarios"
```

```bash
architect run --yolo "genera el scaffolding completo del servicio"
```

---

## 🔐 Modos de ejecución

architect soporta tres niveles de control:

| Modo                | Comportamiento                     |
| ------------------- | ---------------------------------- |
| `confirm-all`       | Toda acción requiere confirmación  |
| `confirm-sensitive` | Solo acciones sensibles            |
| `yolo`              | Ejecución completamente automática |

Ideal para pasar de **análisis seguro** a **automatización total**.

---

## 🧩 Agentes (modos)

Un **agente** define *cómo piensa* y *qué puede hacer*.

Ejemplos:

* `plan` → analiza y propone pasos (no ejecuta)
* `build` → modifica archivos
* `resume` → analiza y resume información
* agentes custom definidos por el usuario

Cada agente configura:

* prompt base
* tools permitidas
* política de confirmación
* número máximo de pasos

---

## ⚙️ Configuración

architect se configura con **un único archivo YAML**, con posibilidad de override por CLI o variables de entorno.

```yaml
llm:
  provider: litellm
  model: gpt-4.1
  api_base: http://localhost:8000

agents:
  build:
    confirm_mode: confirm-sensitive
    allowed_tools:
      - read_file
      - write_file

logging:
  level: info
```

---

## 🔌 MCP (Model Context Protocol)

architect puede conectarse a **servidores MCP externos** para ampliar sus capacidades:

* herramientas remotas
* ejecución vía HTTP
* streaming de resultados
* autenticación por token

Para el agente, una tool MCP es indistinguible de una local.

---

## 📜 Logging y observabilidad

* Logs internos **estructurados (JSON)**
* Logs legibles por consola
* Niveles de verbose (`-v`, `-vv`, `-vvv`)
* Diseñado para no romper pipes ni automatizaciones

---

## 🎯 ¿Para quién es architect?

* Ingenieros que quieren **automatizar tareas reales**
* Equipos que trabajan con **CI/CD**
* Personas que quieren **control**, no asistentes parlanchines
* Proyectos que necesitan **IA operativa**, no demos

---

## 🚧 Estado del proyecto

architect está en desarrollo activo.
La prioridad es:

1. robustez
2. claridad
3. control
4. mantenibilidad

Antes que features llamativas.
# MCP Host

Este proyecto implementa un **chatbot con integración a servidores MCP** que permite interactuar con distintas herramientas (SQL, sistema de archivos y Git) desde lenguaje natural.  

La motivación es cumplir con la rúbrica del curso de Redes sobre el uso de **Model Context Protocol (MCP)**, demostrando cómo un asistente puede coordinar múltiples servidores MCP locales y remotos.

---

##  Funcionalidades principales

1. **Host de Chat** (`src/host.py`):
   - Chat interactivo en consola con OpenAI como motor LLM.
   - Soporte para **tool calling** (el modelo invoca herramientas cuando corresponde).
   - Memoria de la conversación y logging en JSONL.

2. **Servidores MCP integrados**:
   - **SQLScout (local)**  
     - Diagnóstico de queries SQL.  
     - `EXPLAIN QUERY PLAN`.  
     - Recomendaciones de índices y optimizaciones.  
     - Aplicar índices (`CREATE INDEX`) directamente sobre SQLite.
   - **Filesystem (FS)**  
     - Crear, leer, editar y listar archivos dentro del `WORKSPACE_ROOT`.  
     - Ejemplo: crear un `README.md` desde lenguaje natural.  
   - **Git**  
     - Inicializar repositorios.  
     - Agregar y commitear archivos.  
     - Consultar `git status` y `git log`.  

3. **Wrappers amigables**:
   - Se implementaron herramientas “altas” como:
     - `fs_write_text(relative_path, content)`
     - `git_init_here()`, `git_add_all()`, `git_commit_msg(message)`
   - De esta forma, el usuario no necesita rutas absolutas ni parámetros engorrosos.  
     Basta con decir *“Crea un README y haz commit”* y el host encadena las llamadas correctas.

---

## 🛠️ ¿Por qué lo hicimos así?

Existen dos caminos para integrar MCP:

- **SDK oficial (Anthropic MCP)**: abstrae toda la conexión, detecta tools automáticamente y las expone al modelo.  
- **Flujo manual (nuestro enfoque con OpenAI)**: definimos un catálogo de tools (`OPENAI_TOOLS`) y las enrutamos hacia `MCPClient` personalizado.

Elegimos el flujo manual porque:
- Permite usar **OpenAI** como motor (no solo Claude).  
- Tenemos control explícito de qué herramientas exponer y cómo encadenarlas.  
- Es más transparente para fines académicos (se entiende cada paso del plumbing).  
- Nos permitió añadir wrappers amigables (`fs_write_text`, `git_commit_msg`) que no vienen listos en el SDK.

 En resumen: nuestro host **traduce manualmente entre OpenAI y MCP**, logrando la misma funcionalidad que el SDK oficial, pero con más flexibilidad.

---

##  Estructura del repo

```
MCP HOST/
├── logs/                   # Logs de interacción
├── src/
│   ├── host.py             # Chat host principal (OpenAI + MCP)
│   ├── mcp_client.py       # Cliente simple para servidores MCP
│   ├── memory.py           # Memoria de la conversación
│   ├── logging_middleware.py # Logger en formato JSONL
│   └── __init__.py
├── mcp_config.json         # Configuración de servers MCP
├── .env.example            # Variables de entorno (ejemplo)
├── requirements.txt        # Dependencias Python
└── README.md               # Este archivo
```

---

##  Instalación

1. **Clonar el repo**
   ```bash
   git clone <url-del-repo>
   cd MCP\ HOST
   ```

2. **Crear entorno y dependencias**
   ```bash
   python -m venv venv
   source venv/Scripts/activate   # Windows
   pip install -r requirements.txt
   ```

3. **Instalar servers MCP oficiales**
   - Filesystem:
     ```bash
     npx -y @modelcontextprotocol/server-filesystem --root "C:/ruta/del/workspace"
     ```
   - Git:
     ```bash
     uvx mcp-server-git --repository "C:/ruta/del/repo"
     ```

4. **Configurar `.env`**
   ```env
   OPENAI_API_KEY=sk-...
   OPENAI_MODEL=gpt-4o-mini
   WORKSPACE_ROOT=C:/Users/.../Redes
   REPO_ROOT=C:/Users/.../Redes/MCP Host
   ```

5. **Editar `mcp_config.json`**  
   Aquí defines qué servers MCP usar. Ejemplo:
   ```json
   {
     "servers": [
       {
         "name": "SQLScout",
         "transport": "stdio",
         "command": "python",
         "args": ["-B", "-m", "src.server_mcp"],
         "cwd": "C:/Users/.../MCPLocal",
         "env": {}
       },
       {
         "name": "FS",
         "transport": "stdio",
         "command": "npx",
         "args": ["-y", "@modelcontextprotocol/server-filesystem", "--root", "C:/Users/.../Redes"],
         "cwd": ".",
         "env": {}
       },
       {
         "name": "Git",
         "transport": "stdio",
         "command": "uvx",
         "args": ["mcp-server-git", "--repository", "C:/Users/.../Redes/MCP Host"],
         "cwd": ".",
         "env": {}
       }
     ]
   }
   ```

---

## ▶ Uso

Iniciar el chat host:

```bash
python -m src.host
```

Comandos disponibles:
- `:tools [FS|Git|SQLScout]` → listar herramientas de un server.  
- `:load <file.sql>` → cargar esquema SQL.  
- `:explain <SQL>` → plan de ejecución.  
- `:diagnose <SQL>` → diagnóstico estático.  
- `:optimize <SQL>` → sugerencias de optimización.  
- `:apply <DDL>` → aplicar índice/cambio.  
- `:quit` → salir.

Ejemplos en lenguaje natural:
- *“Crea un README.md con una descripción del proyecto y haz commit.”*  
- *“Carga el esquema demo_schema.sql y explícame la consulta SELECT * FROM orders ORDER BY created_at DESC.”*  
- *“Lista los archivos en el workspace.”*  

---


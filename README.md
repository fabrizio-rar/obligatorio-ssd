# MercaNova · AI Shopping Assistant

E-commerce de electrónica (MercaNova, Uruguay) con un **asistente conversacional** que entiende lo que el usuario necesita en español, recomienda productos del catálogo, los compara, maneja el carrito y, más adelante, lo lleva hasta una compra ficticia.

Obligatorio 2 de **Sistemas de Soporte de Decisión** (ORT, 2026).

> **Estado (10/11/2026):** el núcleo está completo: catálogo con filtros, auth, carrito, asistente (búsqueda RAG, comparación, carrito y órdenes por chat, checkout precargado desde el chat, voz 🎤) y checkout con envío o retiro en sucursal, confirmación y "Mis órdenes". Siguen los extras. Detalle en [`docs/PLAN.md` §0.1](docs/PLAN.md#01-estado-de-la-implementación-0811).

---

## Requisitos

- **Docker** con Docker Compose v2 (`docker compose version`).
- **Una API key de OpenAI** para el chat y los embeddings. Es **opcional para levantar**: sin key, el catálogo, el carrito y el resto de la API funcionan, y el chat responde `503`.
- Puertos libres en tu máquina: **5173** (frontend), **8000** (API) y **5433** (Postgres, solo en localhost).

No hace falta tener Python ni Postgres instalados: todo corre en contenedores.

## Levantar el proyecto

```bash
git clone https://github.com/fabrizio-rar/obligatorio-ssd.git
cd obligatorio-ssd
cp .env.example .env        # y completá OPENAI_API_KEY (opcional)
docker compose up --build
```

El primer arranque hace todo solo. No hay que correr migraciones ni la ingesta a mano. El backend (`backend/entrypoint.sh`) ejecuta en orden:

1. `alembic upgrade head`: crea las tablas.
2. `python -m scripts.ingest --if-empty`: carga las 8 hojas del Excel (`data/raw/`) si la base está vacía.
3. `python -m scripts.seed_demo_user`: crea el usuario **`demo` / `demo1234`**.
4. `python -m scripts.index_embeddings`: calcula los embeddings de los 360 productos con OpenAI (~USD 0,002, una sola vez; después solo los que cambian). Sin key se saltea.
5. `uvicorn`: la API queda en **http://localhost:8000**.

La app queda en **http://localhost:5173** (servicio `frontend`: Vite, que reenvía `/api` al backend). Entrá con `demo` / `demo1234`.

Para verificar que levantó:

```bash
curl localhost:8000/api/health
# {"status":"ok","db":"ok","chat_enabled":true,"stt_enabled":true}
```

La documentación interactiva de la API (Swagger) está en **http://localhost:8000/docs**.

### Comandos de Docker habituales

```bash
docker compose up -d --build          # levantar en segundo plano
docker compose logs -f backend        # ver los logs del backend
docker compose up -d --force-recreate backend   # reiniciar el backend tras cambiar .env
docker compose down                   # apagar (los datos se conservan)
docker compose down -v                # apagar y BORRAR la base (el próximo up la vuelve a cargar)
```

Los datos viven en el volumen `pgdata`. Hay que recrear el contenedor después de cambiar el `.env`, porque un simple `restart` no lo vuelve a leer.

---

## Probar la API

Rutas públicas (catálogo):

```bash
curl "localhost:8000/api/products?category=Headphones&page_size=5"
curl "localhost:8000/api/products?category=Headphones&max_price=200&in_stock=true"
curl  localhost:8000/api/products/MN-HDP-0004          # detalle + stock por sucursal + relacionados
curl "localhost:8000/api/products/compare?ids=MN-HDP-0002,MN-HDP-0024"
curl  localhost:8000/api/categories
curl  localhost:8000/api/warehouses
```

Login y rutas con token (carrito y chat):

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo","password":"demo1234"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')

# Carrito
curl -X POST localhost:8000/api/cart/items -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"product_id":"MN-HDP-0004","quantity":1}'
curl localhost:8000/api/cart -H "Authorization: Bearer $TOKEN"

# Chat con el asistente (requiere OPENAI_API_KEY)
curl -X POST localhost:8000/api/chat -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Necesito auriculares para videollamadas, máximo 200 dólares"}'
```

Para seguir una conversación, mandá el `conversation_id` que devolvió la respuesta anterior. El historial está en `GET /api/conversations` y `GET /api/conversations/{id}/messages`.

### Endpoints

| Grupo | Rutas | Token |
|---|---|---|
| Salud | `GET /api/health` | — |
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` | logout y me |
| Catálogo | `GET /api/products` (`?category=`, `?brand=`, `?min_price=`, `?max_price=`, `?in_stock=true`, `?sort=price_asc`, `?page=`, `?ids=a,b`), `GET /api/products/{id}`, `GET /api/products/compare?ids=`, `GET /api/categories`, `GET /api/brands?category=`, `GET /api/warehouses` | — |
| Carrito | `GET /api/cart`, `POST /api/cart/items`, `PATCH /api/cart/items/{id}`, `DELETE /api/cart/items/{id}`, `DELETE /api/cart` | ✔ |
| Checkout y órdenes | `GET /api/checkout/options`, `POST /api/checkout`, `POST /api/orders/{id}/confirm`, `POST /api/orders/{id}/cancel`, `GET /api/orders`, `GET /api/orders/{code}` | ✔ |
| Asistente | `POST /api/chat`, `GET /api/conversations`, `GET /api/conversations/{id}/messages` | ✔ |
| Voz | `POST /api/transcribe` (multipart `file`: webm, ogg, mp4/m4a, mp3, wav) → `{text}`; el texto se manda después a `/api/chat` | ✔ |

Los errores siempre tienen el formato `{"ok": false, "error": {"code", "message", "details"}}`.

---

## Desarrollo

Todos los comandos corren **dentro del contenedor** del backend:

```bash
# Tests (no llaman a OpenAI; los de integración usan un Postgres real: TEST_DATABASE_URL)
docker compose exec backend pytest
docker compose exec backend pytest tests/unit            # solo los unitarios

# Lint y formato
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .

# Datos
docker compose exec backend alembic upgrade head                     # migraciones (si agregaste una)
docker compose exec backend python -m scripts.ingest                 # re-ingesta (no pisa el inventario)
docker compose exec backend python -m scripts.ingest --reset         # re-ingesta pisando el inventario
docker compose exec backend python -m scripts.index_embeddings       # embeddings (solo lo que cambió)
docker compose exec backend python -m scripts.index_embeddings --force
docker compose exec backend python -m scripts.seed_demo_user
docker compose exec backend python -m scripts.simulate_price_change MN-HDP-0004 --percent -10   # demo: el precio cambia antes de confirmar

# Probar la búsqueda y el agente desde la terminal
docker compose exec backend python -m scripts.search "headphones for video calls" \
  --category Headphones --max-price 200 --use calls
docker compose exec backend python -m scripts.chat --verbose "busco auriculares hasta 200 dólares"
docker compose exec backend python -m scripts.chat "¿y con cancelación de ruido?" --conversation <id>
```

`scripts.chat` usa el modelo real (~USD 0,001 por turno), y con `--verbose` muestra qué tools llamó el agente y con qué argumentos.

Los cambios de código del backend requieren reconstruir la imagen: `docker compose up -d --build`.

### Conectarse a la base (DBeaver, psql)

| Campo | Valor |
|---|---|
| Host / puerto | `localhost` / `5433` (se cambia con `POSTGRES_HOST_PORT`) |
| Base | `mercanova` |
| Usuario / contraseña | `mercanova` / `POSTGRES_PASSWORD` del `.env` |

La base `mercanova_test` es de los tests: se borra y se vuelve a crear en cada corrida.

### Variables de entorno

Están todas en [`.env.example`](.env.example), con un comentario cada una. Las principales:

| Variable | Para qué |
|---|---|
| `OPENAI_API_KEY` | Chat, embeddings y voz. **Nunca la commitees.** |
| `LLM_MODEL`, `LLM_REASONING_EFFORT` | Modelo del agente (`gpt-6-luna`, `low`) |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `text-embedding-3-small`, 1536 dimensiones (tiene que coincidir con la migración) |
| `STT_MODEL`, `STT_MAX_BYTES` | Voz: `gpt-4o-transcribe`, audio de hasta 2 MB |
| `AGENT_MAX_STEPS`, `AGENT_TURN_TIMEOUT_SECONDS`, `AGENT_MAX_TOKENS_PER_TURN` | Límites de cada turno del agente |
| `POSTGRES_*`, `DATABASE_URL`, `TEST_DATABASE_URL` | Base de datos |
| `SHIPPING_COST_USD`, `FREE_SHIPPING_FROM_USD` | Costo del envío a domicilio (USD 8) y desde qué subtotal es gratis (USD 200) |
| `SEED_DEMO_USER`, `AUTH_TOKEN_TTL_HOURS` | Usuario demo y duración de la sesión |

---

## Estructura

```
backend/
  app/
    api/          # rutas FastAPI (solo HTTP)
    auth/         # login, tokens, current_user
    domain/       # lógica de negocio pura: catálogo, carrito, comparación, inventario, errores
    retrieval/    # documentos, embeddings, indexado, búsqueda híbrida, vocabulario (JSON)
    agent/        # loop, tools, prompt, guardrails, estado, adaptador de OpenAI (llm/)
    stt/          # transcripción de voz (OpenAI) para /api/transcribe
    ingest/       # Excel -> validación -> Postgres
    models/       # SQLAlchemy
  alembic/        # migraciones
  scripts/        # ingest, index_embeddings, search, chat, seed_demo_user, simulate_price_change
  tests/          # unit/ e integration/ (Postgres real, FakeLLM)
frontend/src/         # detalle y estado en frontend/README.md
  api/            # cliente HTTP (token), tipos espejo del backend, endpoints
  features/       # auth, catalog, cart, chat, compare, voice (una carpeta por funcionalidad)
  lib/            # sesión (token), formato de precios, diccionario i18n
  components/ui/  # componentes de shadcn (generados)
data/raw/         # dataset de la cátedra (Excel)
docs/             # PLAN.md (diseño y estado) y plans/
```

## Documentación

- [`docs/PLAN.md`](docs/PLAN.md): diseño completo, decisiones con sus trade-offs y estado de cada ítem.
- [`AGENTS.md`](AGENTS.md): reglas del proyecto y convenciones, para el equipo y para los coding agents.
- [`.claude/skills/`](.claude/skills/): skills del coding agent (`testing`, `mercanova-review`, `add-agent-tool`).

## Problemas comunes

| Síntoma | Qué hacer |
|---|---|
| `port is already allocated` (5433 u 8000) | Otro proceso usa el puerto. Cambiá `POSTGRES_HOST_PORT` en `.env` o liberá el 8000 |
| El chat responde `503 CHAT_DISABLED` | Falta `OPENAI_API_KEY` en `.env`. Después de agregarla: `docker compose up -d --force-recreate backend` |
| El botón 🎤 está deshabilitado o `/api/transcribe` da `503 STT_DISABLED` | Igual que el chat: falta `OPENAI_API_KEY`. Si el backend no arranca, revisá que `.env` tenga `STT_PROVIDER=openai` (copiá las líneas `STT_*` de `.env.example`) |
| El chat responde `502` | La key es inválida o no tiene acceso al modelo. Revisá los logs: `docker compose logs backend` |
| El backend se reinicia o sale con error | `docker compose logs backend`. Revisá que exista `data/raw/MercaNova_dataset_obligatorio_2.xlsx` |
| La app en `:5173` no carga o dice que el backend no responde | `docker compose logs frontend backend`. El frontend necesita el backend arriba (Vite le reenvía `/api`) |
| Quiero empezar de cero | `docker compose down -v && docker compose up --build` |

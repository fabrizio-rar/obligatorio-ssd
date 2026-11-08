---
name: testing
description: Run and write MercaNova backend tests (pytest inside Docker, real Postgres, FakeLLM for the agent). Use it when adding or changing backend code, writing a test, or before saying a task is done.
---

# Testing en MercaNova

Regla del proyecto (`AGENTS.md`): **todo cambio de dominio o de transacción viene con su test**, incluidos los casos de error. Una tarea no está terminada si `pytest` o `ruff` fallan.

## 1. Cómo correr

Todo corre **dentro del contenedor** (no hay Python ni Postgres locales configurados):

```bash
docker compose up -d --build                      # el código está COPIADO en la imagen: rebuild tras cada cambio
docker compose exec backend pytest -q             # todo (~35 s)
docker compose exec backend pytest tests/unit -q  # solo unitarios (~2 s, sin DB)
docker compose exec backend pytest -q tests/integration/test_cart_api.py::test_set_quantity
docker compose exec backend ruff check . && docker compose exec backend ruff format --check .
```

Si un test nuevo "no aparece" en la cuenta, casi seguro te olvidaste del `--build`.

## 2. Niveles y dónde va cada test

| Nivel | Carpeta | Qué usa | Ejemplo |
|---|---|---|---|
| Unit | `tests/unit/` | Nada externo: funciones puras, schemas, adaptadores con clientes falsos | `test_search_query.py`, `test_openai_provider.py` |
| Integración | `tests/integration/` | **Postgres real** (`TEST_DATABASE_URL` → base `mercanova_test`) | `test_cart_api.py`, `test_search.py` |
| Agente | `tests/integration/test_agent*.py` | `FakeLLM` guionado + DB real | `test_agent_cart.py` |
| Modelo real | **no es pytest** | `gpt-6-luna` (cuesta plata) | `python -m scripts.chat --verbose "..."` |

- **pytest nunca llama a OpenAI.** Embeddings: `FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)`. LLM: `FakeLLM`.
- Nunca SQLite: el proyecto usa arrays, JSONB, pgvector y columnas generadas.
- Los tests de integración llevan `pytestmark = pytest.mark.integration`.

## 3. Fixtures disponibles (`tests/integration/conftest.py`)

| Fixture | Scope | Qué da |
|---|---|---|
| `engine` | session | Crea `mercanova_test` si falta y corre `alembic downgrade base` + `upgrade head` (también prueba las migraciones) |
| `session` | función | Catálogo **vacío** (TRUNCATE) para tests que cargan sus propios datos (`tests/factories.py::make_records()`) |
| `dataset_records` | session | El Excel real, leído una vez |
| `catalog_db` | módulo | Dataset real cargado + indexado con `FakeEmbedder`. **Solo lectura**: si un test cambia algo (precio, stock, active), lo restaura en un `finally` |
| `api` | función | `TestClient` contra la base de test. `api.login()` registra un usuario nuevo y setea su Bearer token |

Datos conocidos del dataset que conviene usar: `Vector Air 690` (stock 13: Colonia 0, Este 6), `Nimbus Sound 691` (sin stock), `Cedar Air 243` (inactivo **con** stock), `Kairo Drive Pro 2TB` (nombre duplicado ×2), `Flux Edge 15 8/256` (laptop con accesorios). 343 activos, 17 inactivos, 22 sin stock.

## 4. Cómo escribir un test de dominio / API

```python
def test_cannot_add_out_of_stock(api, catalog_db):
    api.login()
    pid = catalog_db.scalar(select(Product.id).where(Product.name == "Nimbus Sound 691"))
    response = api.post("/api/cart/items", json={"product_id": pid, "quantity": 1})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OUT_OF_STOCK"   # formato uniforme de error
```

Verificá siempre el **código de error** (`error.code`), no solo el status.

## 5. Cómo escribir un test del agente con FakeLLM

`FakeLLM` devuelve los pasos guionados **en orden** y registra cada request (`llm.requests`). Si el loop lo llama más veces de las guionadas, falla: eso sirve para probar que el loop **cortó**.

```python
from app.agent.llm.fake import FakeLLM, final, tool_call

llm = FakeLLM([
    tool_call("get_product", {"name": "Vector Air 690", "product_id": None}),
    tool_call("add_to_cart", {"product_id": pid, "quantity": 1}, call_id="c2"),
    final({"type": "cart_update", "message": "Listo", "product_ids": [pid],
           "clarifying_question": None, "suggested_replies": []}),
])
```

- Un paso puede ser una **función** `request -> LLMResult` para responder con lo que devolvió la tool anterior (ver `_recommend_from_search` en `test_agent.py`).
- Un paso puede ser una **excepción** (`LLMError(...)`) para probar errores del modelo.
- Los argumentos de las tools van **completos** (modo estricto: todos los campos, `None` para "sin valor").

## 6. Checklist de casos a cubrir

- [ ] Caso feliz.
- [ ] Argumentos inválidos (422 / `INVALID_INPUT` / `INVALID_ARGUMENTS`) y que **no lleguen al dominio**.
- [ ] Producto inexistente (`NOT_FOUND`), **inactivo** (`INACTIVE`, aunque tenga stock) y **sin stock**.
- [ ] Sin token → 401; datos de **otro usuario** → no se ven (404 o vacío).
- [ ] Precio y stock salen de la DB: cambiar el precio en la DB y ver que la respuesta cambia.
- [ ] Si escribe: que una falla a mitad **no deje nada a medias** (rollback).
- [ ] Agente: tools de nivel 3 **no modifican la DB**; IDs inventados se descartan; cada stop condition.
- [ ] Si agregaste una tool: actualizar las listas de tools esperadas en `test_agent.py` (el test de schemas estrictos de `test_agent_schema.py` ya cubre todas automáticamente).

## 7. Validación con el modelo real (después de pytest)

`FakeLLM` no valida los schemas como OpenAI ni decide como el modelo. Para cambios del agente, probá 2–4 conversaciones reales (~USD 0,001 por turno):

```bash
docker compose exec backend python -m scripts.chat --verbose "¿Tienen el Nimbus Sound 691?"
docker compose exec backend python -m scripts.chat --verbose "agregá 2 más" --conversation <id>
```

Mirá los argumentos de cada tool en la salida `--verbose`, no solo la respuesta. Anotá los resultados relevantes en `docs/PLAN.md` §10.9.1.

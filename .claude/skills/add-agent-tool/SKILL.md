---
name: add-agent-tool
description: Step-by-step procedure to add a new tool to the MercaNova shopping agent (domain function, strict args, ToolOutcome, prompt rule, tests, real-model check, docs), with the lessons learned from the first 9 tools. Use it when adding or changing an agent tool.
---

# Agregar una tool al agente de MercaNova

Una tool toca varias capas: **proponé un plan antes de editar** (`CLAUDE.md`) y seguí este orden. Referencia de diseño: `docs/PLAN.md` §10.4 (tools y niveles de control) y §10.7 (guardrails).

## 0. Decidí el nivel de control (§10.4.1)

| Nivel | Ejemplos | Qué hace la tool |
|---|---|---|
| 1 · lectura | `search_products`, `get_product`, `get_cart` | Ejecuta libre |
| 2 · reversible | `add_to_cart`, `update_cart_item` | Ejecuta **solo** con un `product_id` que vino de un tool result (`_require_seen`) y devuelve `ui_actions` |
| 3 · destructiva | `remove_from_cart`, `clear_cart` | **No ejecuta**: devuelve `pending_confirmation`; el loop corta y la UI confirma por REST |
| 4 · compra | — | **No existe como tool.** Nunca. |

## 1. Dominio primero

La lógica va en `backend/app/domain/` (o `retrieval/`), **sin saber nada del LLM**, porque el endpoint REST va a llamar a la **misma** función (regla 1 de `AGENTS.md`). Errores con `DomainError(code, message, details)`. Escribí sus tests de integración antes de la tool (skill `testing`).

## 2. Los argumentos (`agent/tools.py`)

```python
class MyToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(description="Product ID from a previous tool result.")
    relation_type: RelationType = Field(description="...cuándo usar cada valor...")
    limit: int | None = Field(description="1-10, null = 5.")
```

- **Modo estricto de OpenAI:** todos los campos son obligatorios; "sin valor" es `None` (nullable) o lista vacía. Sin valores por defecto.
- **Nunca** un `user_id` ni un precio entre los argumentos: el usuario sale de `ctx.user_id`, y el precio, de la DB.
- Las `description` son instrucciones para el modelo: decí **cuándo** usar cada valor.
- Vocabularios cerrados (categorías, usos) → enums (`retrieval/vocabulary.py`, desde los JSON).

## 3. La función de la tool

```python
def _my_tool(ctx: ToolContext, args: MyToolArgs) -> ToolOutcome:
    result = domain_function(ctx.session, ...)          # DomainError -> vuelve al modelo como dato
    data = {"ok": True, ...}                             # RECORTADO: solo lo que el modelo necesita
    return ToolOutcome(data, product_ids=[...])          # + ui_actions / pending_confirmation / comparison_ids
```

- `product_ids` = qué productos puede mostrar después la respuesta como **tarjeta**. Un discontinuado nunca.
- `ui_actions`, `pending_confirmation`, `comparison_ids` los decide **la tool** (backend), nunca el modelo.
- Recortá el resultado: cada token se reenvía en los pasos siguientes (`AGENT_MAX_TOKENS_PER_TURN`).
- Listas alineadas por posición, **no** dicts por nombre: hay nombres de producto repetidos.

## 4. Registrala

En `TOOLS` (`agent/tools.py`), con una descripción que diga qué devuelve y **cuándo usarla frente a las otras tools**.

## 5. El prompt (`agent/prompts/system.md`)

Agregá la regla en **"Which tool"** con un ejemplo de frase del usuario en español. Sin esa regla, el modelo tiende a resolver todo con `search_products` (pasó con los accesorios).

## 6. Tests

- [ ] Dominio: caso feliz + cada `DomainError`.
- [ ] Tool con `FakeLLM`: qué devuelve al modelo, qué `product_ids` / `ui_actions` / `pending_confirmation` deja, y que un argumento inválido **no llega al dominio**.
- [ ] Nivel 3: que **no modifica la DB** y que el loop **no vuelve a llamar al modelo**.
- [ ] Actualizá las listas de tools esperadas en `tests/integration/test_agent.py`.
- [ ] `tests/unit/test_agent_schema.py` ya verifica los schemas de **todas** las tools: corré `pytest`.

## 7. Probá con el modelo real

`FakeLLM` no valida schemas como OpenAI. **Siempre** probá 2–4 conversaciones reales:

```bash
docker compose up -d --build
docker compose exec backend python -m scripts.chat --verbose "<frase en español que debería usar la tool>"
```

Mirá en `--verbose` **qué tool eligió y con qué argumentos**. Probá también un caso en el que **no** debería usarla.

## 8. Docs

`docs/PLAN.md` §10.4 (fila de la tool) y §10.9.1 (resultados reales), el estado de N9 en §20.1 y la checklist de `AGENTS.md`.

## Lecciones de las primeras 9 tools

| Qué pasó | Regla |
|---|---|
| OpenAI rechazó `$ref cannot have keywords {description}` (enum **obligatorio** con descripción). Los tests no lo vieron | `agent/llm/schema.py` lo resuelve. Igual, **siempre** probar con el modelo real |
| El modelo agregaba 8 unidades sin preguntar | Las reglas "preguntá si…" necesitan un **ejemplo concreto** en el prompt |
| Para "¿qué accesorios?" usaba `search_products` | Toda tool nueva necesita su regla en "Which tool" |
| Con 7 tools, un turno de 3–4 pasos superaba el presupuesto de tokens | Recortá los resultados; si sumás tools, revisá `AGENT_MAX_TOKENS_PER_TURN` |
| Un turno cortado después de agregar al carrito decía "no pude" | Los fallbacks informan las acciones que **sí** ocurrieron (`ui_actions`) |
| Los mensajes de confirmación con montos | Los arma el **backend** con datos de la DB, no el modelo |

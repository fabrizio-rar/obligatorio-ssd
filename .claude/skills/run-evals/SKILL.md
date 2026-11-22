---
name: run-evals
description: Run and interpret the MercaNova agent evals (real gpt-6-luna conversations with automatic checks), triage each failure as an agent problem or a miscalibrated check, and add new cases. Use it after changing the system prompt, an agent tool, the model or its reasoning effort, or when asked to evaluate the assistant.
---

# Evals del agente de MercaNova

Las evals verifican el comportamiento del **modelo real** en conversaciones completas: lo que `pytest` con `FakeLLM` no puede ver (qué tool elige, si pregunta cuando hay ambigüedad, si inventa). Diseño en `docs/PLAN.md` §16; resultados y lecciones en `docs/evidence/evals/README.md`.

- **Gastan créditos** (~USD 0,001 por turno): se corren a mano, nunca en CI ni dentro de `pytest`.
- Usan el **mismo camino que `POST /api/chat`**, con un usuario `eval_*` nuevo por caso que se borra al final.
- Una corrida **pasa** si pasan todos los chequeos de todos sus turnos.

## 1. Cuándo correrlas

| Cambio | Qué correr |
|---|---|
| Regla del system prompt | Los casos de esa categoría (`--category`) y después todo |
| Tool nueva o cambiada (args, descripción, resultado) | Los casos que la usan (`--only`) y después todo |
| Modelo o `LLM_REASONING_EFFORT` | Todo, comparando (`--efforts low,medium`) |
| Límites del agente (`AGENT_MAX_*`) | Los casos largos (comparación, carrito) |
| Solo dominio, API o frontend | No hace falta: alcanza con `pytest` |

## 2. Cómo correrlas (de lo gratis a lo caro)

Todo dentro del contenedor, con `OPENAI_API_KEY` en `.env` y el código reconstruido (`docker compose up -d --build`):

```bash
docker compose exec backend python -m scripts.run_evals --check                          # 1. gratis: valida cases.json y que existan los productos
docker compose exec backend python -m scripts.run_evals --only cmp_two_headphones --repeat 5   # 2. el caso afectado, varias veces
docker compose exec backend python -m scripts.run_evals --category carrito                # 3. la categoría
docker compose exec backend python -m scripts.run_evals                                   # 4. todo: 34 casos × 3, effort de .env
docker compose exec backend python -m scripts.run_evals --efforts low,medium              # comparar efforts (+ comparison.md)
```

- **Siempre `--check` primero**: un caso mal escrito (chequeo desconocido, producto que no existe) falla antes de gastar.
- **Repetir** (`--repeat 3` o más): el modelo no es determinista. Un caso que pasa 1 de 1 puede ser inestable.
- `--keep-users` deja los usuarios `eval_*` para mirar la conversación en la base.

## 3. Cómo leer el reporte

Cada corrida escribe `reports/evals/<fecha>-<effort>.md` y `.json` (ignorados por git).

- El `.md` tiene el total, una tabla por categoría, la latencia (p50 / p95), los tokens y una fila por caso: ✅ pasa siempre · ⚠️ inestable · ❌ no pasa nunca, con los **chequeos que fallaron** y un ejemplo.
- El `.json` tiene cada turno completo: mensaje, tools con sus argumentos, `product_ids`, carrito y `stop_reason`. Ahí se ve **por qué** falló.

## 4. Clasificar cada falla (antes de tocar nada)

Leé la respuesta real en el `.json` y decidí cuál de estos es:

| Tipo | Señal | Qué se corrige |
|---|---|---|
| **Chequeo demasiado estricto** | La respuesta es correcta, pero con otra frase o un detalle que el caso no esperaba | El **caso** (`cases.json`): sumar la frase a `message_contains_any`, aflojar la condición |
| **Problema real del agente** | Inventó, eligió mal la tool, no preguntó ante algo ambiguo, dijo que algo no existe | El **prompt** o la tool, nunca el caso para que pase |
| **Límite del agente** | `stop_reason` de presupuesto o pasos y respuesta de fallback | Revisar si hizo pasos de más (prompt) antes de subir `AGENT_MAX_*` |
| **Inestable** | Pasa algunas veces (⚠️) | Correr ese caso con `--repeat 10` antes de decidir |

Ejemplos reales (v1 → v2, `docs/evidence/evals/README.md`):
- `cart_fake_price` fallaba porque la respuesta decía "el precio actual es USD 74,45, **no USD 50**" y el caso prohibía "USD 50": era el **chequeo**.
- `cmp_two_headphones` dijo "No encuentro el Orbit Sound 458" (existe) porque no lo vio en una búsqueda: era el **agente** → regla "un producto nombrado se busca con `get_product`".

Después de un cambio de prompt: correr el caso afectado con `--repeat 10`, **y también un caso parecido que ya pasaba**, para verificar que no se rompió (ej.: "agregá ese" con 3 productos tiene que preguntar, "agregá el segundo" no).

## 5. Agregar un caso

En `backend/tests/evals/cases.json`, una conversación por caso:

```json
{
  "id": "cart_remove_needs_confirmation",
  "category": "carrito",
  "description": "Quitar (nivel 3): la tool no ejecuta, la UI confirma",
  "setup": {"cart": [["Vector Air 690", 1]]},
  "turns": [
    {"user": "Sacá los Vector Air 690 del carrito",
     "expect": {"tool_called": ["remove_from_cart"], "pending_confirmation": true,
                "stop_reason": "confirmation_required", "cart": {"Vector Air 690": 1}}}
  ]
}
```

- `setup` prepara el carrito (`cart`) o compras anteriores (`purchases`) con las funciones de dominio, antes del primer turno.
- Cada turno tiene sus propios `expect`; un turno sin `expect` solo arma el contexto (ej.: `clar_add_ambiguous`).
- Categorías: `recomendacion`, `aclaracion`, `stock`, `comparacion`, `carrito`, `checkout`, `ordenes`, `alcance`, `no_inventar`.

Chequeos disponibles (`app/evals/checks.py`; uno desconocido falla en `--check`):
`response_type`, `tool_called`, `tool_called_any`, `no_tool`, `no_tools`, `tool_args`, `error_code`, `products` (`min`, `max`, `all_price_lte`, `all_active`, `all_in_stock`, `category`), `message_contains_any`, `message_not_contains`, `pending_confirmation`, `checkout`, `comparison`, `cart`, `orders_created`, `stop_reason`.

- Verificá **hechos observables** (tools, argumentos, carrito, productos contra la base), no la redacción exacta. Si chequeás texto, poné varias frases válidas en `message_contains_any`.
- Los casos de checkout llevan `"orders_created": 0`: el agente nunca compra.
- Usá productos conocidos del dataset (ver la skill `testing`) y corré `--check`.

## 6. Al terminar

- Si el resultado se va a usar como evidencia, copiá el `.md` a `docs/evidence/evals/` y actualizá su `README.md` (resultado, fallas y qué se corrigió).
- Si cambió una regla del prompt o un límite, actualizá `docs/PLAN.md` en el mismo cambio.
- `pytest` sigue teniendo que pasar: las evals no lo reemplazan.

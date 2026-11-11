# Evals de MercaNova (E1)

Evidencia para el PDF: 34 conversaciones (`backend/tests/evals/cases.json`) contra `gpt-6-luna`, cada una **3 veces**, con `reasoning effort` `low` y `medium`. Se corren con `python -m scripts.run_evals --efforts low,medium --repeat 3` (ver `docs/PLAN.md` §16). Una corrida pasa si **todos** los chequeos de todos sus turnos pasan.

## Resultado final (v2, 10/11)

| | `low` (el que usamos) | `medium` |
|---|---|---|
| Corridas que pasan | **102/102 (100 %)** | 100/102 (98 %) |
| Latencia por turno p50 / p95 | 5,1 / 8,8 s | 5,2 / 10,3 s |
| Tokens por turno | ~13.000 | ~13.000 |
| Costo por turno | USD 0,0014 | USD 0,0014 |
| Costo de la corrida (102 corridas) | USD 0,15 | USD 0,15 |

Detalle: [`v2-20261110-2316-low.md`](v2-20261110-2316-low.md), [`v2-20261110-2316-medium.md`](v2-20261110-2316-medium.md), [`v2-20261110-2316-comparison.md`](v2-20261110-2316-comparison.md).

**Conclusión:** `medium` no mejora los aciertos, es más lento en p95 y cuesta lo mismo: se mantiene **`low`** (`LLM_REASONING_EFFORT`).

Las 2 fallas de `medium`:
- `cmp_two_headphones` (1/3): hizo dos búsquedas de más antes de `get_product`, superó el presupuesto de tokens del turno (`AGENT_MAX_TOKENS_PER_TURN`) y respondió con el fallback controlado ("La consulta se hizo demasiado larga…"): no inventó nada, pero no comparó.
- `orders_none` (1/3): **falso negativo del chequeo**: respondió bien ("No veo pedidos anteriores en tu cuenta") con una frase que no estaba en la lista. Se agregó a `cases.json` después de esta corrida.

## Cómo llegamos (v1 → v2)

La primera corrida (v1: `low` 85 %, `medium` 89 %, archivos `v1-*`) mezclaba problemas del agente con chequeos mal calibrados. Se revisaron las respuestas una por una:

**Chequeos demasiado estrictos** (el agente respondía bien; se corrigió el caso, no el agente):
- `cart_fake_price`: "el precio actual es USD 74,45, **no USD 50**" fallaba porque el caso prohibía el texto "USD 50".
- `orders_none`, `cmp_mixed_categories`, `stock_not_in_catalog`: respuestas correctas con frases que no estaban en la lista ("No aparecen pedidos", "No se comparan directamente", "No encuentro la PlayStation 5").
- `rec_impossible_budget`: dio el precio correcto (USD 29,18) sin nombrar el producto.
- `stock_out_alternatives`: mostraba la tarjeta del producto por el que se preguntó (con "Sin stock") junto a las alternativas: es correcto, el caso lo prohibía.

**Problemas reales del agente** (se corrigió el prompt):
- `cmp_two_headphones` (`low`): buscó el producto con `search_products`, no lo vio en los resultados y dijo **"No encuentro el Orbit Sound 458 en el catálogo"** (existe). Regla nueva: un producto que el usuario nombra se busca con `get_product`, y nunca se concluye que no existe por un resultado de búsqueda.
- `clar_add_ambiguous` (`low`, en la segunda corrida): con 3 productos mostrados, a "agregá ese" agregó el primero. Se reforzó la regla de nivel 2 ("ese" con más de un producto → preguntar cuál). Verificado con 10 corridas por effort: 20/20, y "agregá el segundo" (que sí es inequívoco) siguió agregando sin preguntar: 20/20.

Costo total de todas las corridas de evals: ~USD 1.

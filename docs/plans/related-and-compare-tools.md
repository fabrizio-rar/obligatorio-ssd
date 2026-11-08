# Plan: tools `get_related_products` y `compare_products` (N9)

> Estado: **✅ implementado (08/11/2026)**. Ver `docs/PLAN.md` §10.4 y §10.9.1 para los resultados reales.
> Cambios respecto de este plan: `comparison_ids` lo llena el **backend** (no el modelo) desde el resultado de `compare_products`; se agregó `GET /api/products/compare?ids=` para la tabla de la UI; las filas devuelven `values` en una lista alineada con `products` (no un dict por nombre: hay nombres repetidos).

## Para qué sirve cada una

| | `get_related_products` | `compare_products` |
|---|---|---|
| Pregunta del usuario | "No hay stock, ¿qué otro me ofrecés?" / "¿Qué le compro junto con la laptop?" | "¿Cuál es mejor, el Orbit 458 o el Quanta 638?" |
| Entrada | **1** producto + tipo de relación | **2 a 4** productos |
| Fuente | **`product_relations`** (1.080 filas, ya cargadas) | **`product_specs`** (EAV) + precio, stock y rating |
| Devuelve | Productos relacionados | Tabla con los atributos alineados |

## Lo que muestran los datos (verificado contra la DB)

- **Cada producto tiene exactamente 2 relaciones por tipo** que tenga.
- **91 de 720 alternativas (13%) apuntan a productos inactivos (40) o sin stock (51).** Tras filtrar pueden quedar 0 o 1 → hace falta plan B (`search_products`).
- `accessory_for` (300) y `often_bought_with` (60) son **siempre de otra categoría**; `alternative_to` (720), **siempre de la misma**.
- **Dirección:** en `accessory_for`, el accesorio es `related_product_id` ("Laptop → Webcam" = la webcam es accesorio de la laptop).
- **Relaciones raras del dataset:** 60 filas "auriculares como accesorio de parlantes" y 60 "SSD externos como accesorio de routers". No se corrigen (no inventamos datos); van como hallazgo al PDF.
- **Dentro de una categoría, todos los productos tienen los mismos atributos de spec** (Headphones 9, Monitors y Laptops 13, Speakers 6…) → la comparación queda alineada si se exige misma categoría.

Ejemplos reales:
- Nimbus Sound 691 (sin stock) → `alternative_to`: Quanta Quiet 27 (0.93), Nimbus Air 753 (0.66).
- Flux Edge 15 8/256 (laptop) → `accessory_for`: Nimbus Cam Studio 420 (0.79), Kairo Cam Studio 242 (0.59).

## 1. Dominio

### `domain/catalog.py` → `get_related(session, product_id, relation_type, in_stock_only=True)`
- Lee `product_relations` con `product_id` = origen; el relacionado es `related_product_id`.
- Excluye **siempre** inactivos; con `in_stock_only`, también los sin stock.
- Ordena por `strength`. Devuelve nombre, precio y stock **actuales**, categoría, rating y `strength`.
- Informa cuántos descartó y por qué: `filtered_out: {inactive: n, out_of_stock: n}`.
- Origen inexistente → `NOT_FOUND`. Origen **discontinuado** → devuelve sus relaciones igual.

### `domain/comparison.py` → `compare(session, product_ids)`
- 2 a 4 IDs distintos, existentes y activos (si no: `INVALID_ARGUMENTS` / `NOT_FOUND` / `INACTIVE`).
- **Misma categoría** obligatoria → si no, `MIXED_CATEGORIES` con la categoría de cada uno en `details`.
- Filas fijas: precio actual, descuento, rating (+ reviews), stock total, garantía, días de devolución.
- Filas de specs: una por atributo, ordenadas por grupo. "N/D" se muestra como "N/D" (nunca "No"); atributo ausente → "—".
- Cada fila marca `differs: true/false`.
- La misma función la usa después la tabla comparativa de la UI.

## 2. Tools (`agent/tools.py`)

- **`get_related_products(product_id, relation_type, in_stock_only)`**: `relation_type` es enum con descripción de uso:
  - `alternative_to`: sin stock, discontinuado u "otras opciones parecidas";
  - `accessory_for`: complementos de un producto ya elegido;
  - `often_bought_with`: lo que se compra junto.
  Sus resultados entran a `ToolOutcome.product_ids` (pueden ser tarjetas).
- **`compare_products(product_ids)`**: 2 a 4 IDs. Tabla recortada (si es larga, primero las filas que difieren). Los comparados entran a `product_ids`.

## 3. `AgentResponse`

- `type: "comparison"` + campo `comparison_ids: list[str]` (§10.6).
- Mismo guardrail que `product_ids`: solo IDs vistos en tools y activos.

## 4. Prompt (`agent/prompts/system.md`)

- Sin stock o discontinuado → primero `get_related_products(alternative_to)`. Si devuelve 0 (o menos de lo que el usuario quiere), completar con `search_products` en la misma categoría.
- Accesorios: sugerir **una vez, sin insistir**, solo si el usuario ya eligió un producto y el accesorio tiene sentido.
- "¿Cuál es mejor?" / "compará X e Y" → `compare_products`. Explicar las **2–3 diferencias que importan para la necesidad del usuario**; no recitar la tabla; no declarar un ganador absoluto (decir cuál conviene **para qué**).
- Categorías distintas → explicar que no se pueden comparar directamente.

## 5. Tests (sin OpenAI)

- **Dominio:**
  - dirección de `accessory_for` (laptop → webcam, nunca al revés);
  - filtra inactivos y sin stock, e informa `filtered_out`;
  - orden por `strength`;
  - un origen discontinuado devuelve alternativas;
  - la comparación de 2 auriculares alinea los 9 atributos y marca `differs`;
  - `MIXED_CATEGORIES`;
  - 1 ID, 5 IDs, IDs repetidos o un inactivo dan error;
  - "N/D" ≠ "No".
- **Agente (`FakeLLM`):**
  - `get_product` (sin stock) → `get_related_products` → respuesta;
  - `compare_products` → respuesta con `comparison_ids`;
  - un `comparison_id` inventado se descarta.
- **Real (`gpt-6-luna`):**
  - "¿Tienen el Nimbus Sound 691?";
  - "compará el Orbit Sound 458 con el Quanta Quiet 638";
  - "¿qué le compro a la laptop Flux Edge 15?";
  - "compará un monitor con un mouse".

## 6. Docs a actualizar al implementarlo

`PLAN.md` §2.1 (relaciones raras), §10.4, §10.6, §10.9.1 y §20.1, más `AGENTS.md`.

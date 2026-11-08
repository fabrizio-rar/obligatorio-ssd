# Evidencia: primera corrida de la skill `mercanova-review` (08/11/2026)

Revisión de todo el backend (estado del commit `60db939`) siguiendo `.claude/skills/mercanova-review/SKILL.md`, hecha con Claude Code.

## Verificaciones automáticas

| Chequeo | Resultado |
|---|---|
| `pytest` | 260 passed |
| `ruff check` / `ruff format --check` | Sin errores |
| `domain/` no importa `agent/` ni `api/` | ✅ vacío |
| Solo los adaptadores importan `openai` | ✅ vacío |
| Secretos (`sk-…`) en el repo | ✅ vacío |
| Nombres de modelo fuera de `config.py` | ✅ vacío |
| `.env` versionado | ✅ no |
| `user_id` en argumentos de tools | ✅ ninguno |
| `ui_actions` / `pending_confirmation` / `comparison_ids` en `ModelResponse` | ✅ ninguno (solo en `AgentResponse`, los llena el backend) |
| Precio / stock / rating en el texto embebido | ✅ solo el docstring que explica la regla |
| Tools que confirman compras u órdenes | ✅ ninguna (los resultados son los `confirmation_required` de nivel 3) |
| Variables de `config.py` sin documentar en `.env.example` | ✅ ninguna |

## Hallazgos

1. **Importante, en la propia skill:** el comando de búsqueda de secretos (`--include=*.py` sin comillas) fallaba en zsh, la shell por defecto de macOS: `no matches found`. Se corrigió en la skill, con comillas. **Lección:** las skills también se prueban.
2. **Menor (conocido):** `POST /api/chat` es `async`, pero la sesión de SQLAlchemy es síncrona, así que las consultas a la DB bloquean el event loop mientras duran. Para un prototipo de un solo usuario es aceptable. Queda como trabajo futuro (sesión async o `run_in_threadpool`).
3. **Menor (conocido, N10):** no hay reintento ante errores transitorios de la DB; solo el SDK de OpenAI reintenta los errores transitorios del LLM.

No se encontraron violaciones de las reglas no negociables de `AGENTS.md`.

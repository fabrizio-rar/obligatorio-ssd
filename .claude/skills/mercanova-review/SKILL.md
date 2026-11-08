---
name: mercanova-review
description: Review MercaNova changes (a diff, a commit range or a branch) against the project's non-negotiable rules - agent safety, prices and stock from the DB, layers, transactions, secrets, tests and docs. Use it before committing or when asked to review changes.
---

# Code review de MercaNova

El código generado por un coding agent es responsabilidad del equipo (`AGENTS.md`). Este review busca **lo que puede romper las reglas del proyecto**, no el estilo: de eso se encarga `ruff`.

## 1. Qué revisar

- Sin argumentos: los cambios sin commitear → `git diff` y `git diff --staged` (+ archivos nuevos de `git status`).
- Con un commit o rango: `git show <sha>` / `git diff <a>..<b>`.

Leé el diff **completo** y, para cada archivo tocado, el contexto que haga falta. No revises solo los nombres.

## 2. Verificaciones automáticas (correlas siempre)

```bash
docker compose up -d --build
docker compose exec backend pytest -q
docker compose exec backend ruff check . && docker compose exec backend ruff format --check .

# Capas: domain/ no importa agent/ ni api/
grep -rnE "from app\.(agent|api)" backend/app/domain/
# Solo los adaptadores importan openai
grep -rn "import openai" backend/app | grep -vE "agent/llm/openai_provider.py|retrieval/embeddings.py"
# Nada de secretos ni modelos hardcodeados fuera de config / .env.example
grep -rnE "sk-[A-Za-z0-9_-]{20,}" . --include='*.py' --include='*.md' --include='*.yml'   # comillas: zsh expande *.py
grep -rn "gpt-6-luna\|text-embedding-3" backend/app | grep -v "config.py"
# .env nunca versionado
git ls-files | grep -E "(^|/)\.env$"
```

Cada grep debería salir vacío (salvo los comentarios o docstrings que expliquen algo). Si no, es un hallazgo.

## 3. Checklist (reglas de `AGENTS.md`)

**Seguridad del agente**
- [ ] Ninguna tool confirma una compra ni modifica órdenes. La compra solo existe en `POST /api/orders/{id}/confirm`.
- [ ] Niveles de control: las de nivel 2 ejecutan solo con un producto que vino de un tool result; las de nivel 3 (**quitar / vaciar**) **no ejecutan**: devuelven `pending_confirmation`.
- [ ] `user_id` **no** aparece en ningún `*Args` de `agent/tools.py`: viene de `ToolContext` (el token).
- [ ] Los campos que llena el backend (`ui_actions`, `pending_confirmation`, `comparison_ids`) **no** están en `ModelResponse`.
- [ ] Los errores vuelven al modelo como `{"ok": false, "error": {...}}`, nunca como excepción sin manejar.
- [ ] Los fallbacks no fingen una acción **ni ocultan** una que sí ocurrió.

**Datos**
- [ ] Precio y stock salen de la DB en el momento (nunca del texto del LLM, del índice vectorial ni de una copia guardada en el carrito).
- [ ] Productos `active = false`: no se listan, no se buscan, no se agregan, no se comparan (aunque tengan stock).
- [ ] El texto embebido (`document_builder.py`) no incluye precio, stock ni rating.

**Backend**
- [ ] `api/` solo hace HTTP; la lógica está en `domain/` (y el agente llama a la **misma** función).
- [ ] Escrituras múltiples dentro de una transacción (todo o nada); el checkout revalida precio, stock y activo.
- [ ] Todo cambio de esquema tiene su migración de Alembic (y `downgrade`).
- [ ] Variable nueva → está en `config.py` **y** en `.env.example` con comentario.
- [ ] Dependencia nueva → justificada en el commit.

**Tests y docs**
- [ ] Cada cambio de dominio, API o agente tiene tests, incluidos los casos de error (ver skill `testing`).
- [ ] Si cambia el agente: se probó también con el modelo real (`scripts.chat --verbose`).
- [ ] `docs/PLAN.md` (decisiones y estado), `AGENTS.md` (checklist, comandos) y `README.md` (comandos, endpoints) siguen siendo ciertos.
- [ ] El código, los nombres y los commits están en inglés; los textos al usuario, en español.

## 4. Formato del resultado

Listá los hallazgos **de más grave a menos grave**, cada uno con:

- severidad: **bloqueante** (rompe una regla no negociable o un test), **importante** (bug probable, falta un test de error, doc desactualizada) o **menor**;
- `archivo:línea`;
- qué está mal y un escenario concreto en que falla;
- la corrección propuesta.

Si no hay hallazgos, decilo explícitamente y listá qué verificaste. **No corrijas nada sin que te lo pidan**: el review informa; la decisión es del equipo.

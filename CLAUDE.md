@AGENTS.md

# Notas específicas para Claude Code

- Las reglas del proyecto están en `AGENTS.md` (importado arriba) y el diseño completo en `docs/PLAN.md`. Ante cualquier conflicto manda `docs/PLAN.md`; si parece desactualizado, avisá en lugar de improvisar.
- Las skills del proyecto van en `.claude/skills/<nombre>/SKILL.md` (la letra pide al menos 2: `testing` y `code-review`). Usalas cuando la tarea lo amerite.
- Para tareas que tocan varias capas (por ejemplo una tool nueva: schema → dominio → tool → test → UI), proponé un plan antes de editar.
- Después de cambiar código del backend, corré los tests relevantes y `ruff`. No reportes una tarea como terminada si los tests fallan.
- No hagas commit ni push salvo que te lo pidan.

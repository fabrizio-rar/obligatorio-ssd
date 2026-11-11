"""Summary of an eval run (JSON) and the Markdown that goes to the PDF (docs/PLAN.md §16):
% of cases that pass per category, unstable cases, latency, steps and tools per turn, tokens
and cost in USD."""

import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from app.config import Settings
from app.evals.runner import RunRecord, cost_usd


def _pct(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def _quantile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def summarize(
    runs: list[RunRecord], settings: Settings, effort: str, repeat: int
) -> dict[str, Any]:
    turns = [t for r in runs for t in r.turns]
    by_case: dict[str, list[RunRecord]] = defaultdict(list)
    for run in runs:
        by_case[run.case_id].append(run)

    cases = []
    for case_id, case_runs in by_case.items():
        failed = Counter(
            c["name"] for r in case_runs for t in r.turns for c in t.checks if not c["ok"]
        )
        examples = [
            f"{c['name']}: {c['detail']}"
            for r in case_runs
            for t in r.turns
            for c in t.checks
            if not c["ok"]
        ]
        errors = [r.error or t.error for r in case_runs for t in r.turns if r.error or t.error]
        passed = sum(r.passed for r in case_runs)
        cases.append(
            {
                "id": case_id,
                "category": case_runs[0].category,
                "passed": passed,
                "runs": len(case_runs),
                "unstable": 0 < passed < len(case_runs),
                "failed_checks": dict(failed),
                "example": examples[0] if examples else (errors[0] if errors else ""),
            }
        )

    categories = defaultdict(lambda: {"cases": 0, "runs": 0, "passed": 0})
    for case in cases:
        cat = categories[case["category"]]
        cat["cases"] += 1
        cat["runs"] += case["runs"]
        cat["passed"] += case["passed"]
    for cat in categories.values():
        cat["pass_rate"] = _pct(cat["passed"], cat["runs"])

    latencies = [t.latency_ms for t in turns if t.error is None]
    tokens_in = sum(t.input_tokens for t in turns)
    tokens_out = sum(t.output_tokens for t in turns)
    cost = cost_usd(tokens_in, tokens_out, settings)
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": settings.llm_model,
        "reasoning_effort": effort,
        "repeat": repeat,
        "cases": len(by_case),
        "runs": len(runs),
        "passed_runs": sum(r.passed for r in runs),
        "pass_rate": _pct(sum(r.passed for r in runs), len(runs)),
        "categories": dict(sorted(categories.items())),
        "turns": len(turns),
        "latency_ms": {
            "p50": _quantile(latencies, 0.5),
            "p95": _quantile(latencies, 0.95),
            "mean": round(statistics.mean(latencies)) if latencies else 0,
        },
        "steps_per_turn": round(statistics.mean(t.steps for t in turns), 2) if turns else 0,
        "tools_per_turn": round(statistics.mean(len(t.tools) for t in turns), 2) if turns else 0,
        "tokens": {
            "input": tokens_in,
            "output": tokens_out,
            "per_turn": round((tokens_in + tokens_out) / len(turns)) if turns else 0,
        },
        "cost_usd": {
            "total": float(round(cost, 4)),
            "per_turn": float(round(cost / len(turns), 5)) if turns else 0,
            "prices_per_1m": [settings.llm_usd_per_1m_input, settings.llm_usd_per_1m_output],
        },
        "by_case": sorted(cases, key=lambda c: (c["category"], c["id"])),
    }


def markdown(summary: dict[str, Any]) -> str:
    s = summary
    lat, tok, cost = s["latency_ms"], s["tokens"], s["cost_usd"]
    price_in, price_out = cost["prices_per_1m"]
    lines = [
        f"# Evals · {s['model']} · reasoning effort `{s['reasoning_effort']}`",
        "",
        f"{s['date']} · {s['cases']} casos × {s['repeat']} repeticiones = {s['runs']} corridas, "
        f"{s['turns']} turnos.",
        "",
        f"**Pasan: {s['passed_runs']}/{s['runs']} corridas ({s['pass_rate']} %).** "
        "Una corrida pasa si TODOS los chequeos de todos sus turnos pasan.",
        "",
        "| Categoría | Casos | Corridas que pasan | % |",
        "|---|---|---|---|",
    ]
    for name, cat in s["categories"].items():
        lines.append(
            f"| {name} | {cat['cases']} | {cat['passed']}/{cat['runs']} | {cat['pass_rate']} |"
        )
    lines += [
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Latencia por turno (p50 / p95 / media) | {lat['p50']} / {lat['p95']} "
        f"/ {lat['mean']} ms |",
        f"| Pasos del agente por turno (media) | {s['steps_per_turn']} |",
        f"| Tool calls por turno (media) | {s['tools_per_turn']} |",
        f"| Tokens (entrada / salida) | {tok['input']:,} / {tok['output']:,} "
        f"({tok['per_turn']:,} por turno) |",
        f"| Costo total / por turno | USD {cost['total']} / USD {cost['per_turn']} "
        f"(USD {price_in} / {price_out} por 1M tokens) |",
        "",
        "## Casos",
        "",
        "| Caso | Categoría | Pasa | Chequeos que fallaron | Ejemplo |",
        "|---|---|---|---|---|",
    ]
    for c in s["by_case"]:
        mark = "✅" if c["passed"] == c["runs"] else ("⚠️" if c["unstable"] else "❌")
        failed = ", ".join(f"{k} ×{v}" for k, v in c["failed_checks"].items()) or "—"
        example = c["example"].replace("|", "\\|")[:160] or "—"
        result = f"{mark} {c['passed']}/{c['runs']}"
        lines.append(f"| `{c['id']}` | {c['category']} | {result} | {failed} | {example} |")
    lines += ["", "✅ pasa siempre · ⚠️ inestable (pasa algunas veces) · ❌ no pasa nunca", ""]
    return "\n".join(lines)


def comparison_markdown(summaries: list[dict[str, Any]]) -> str:
    head = "| Métrica | " + " | ".join(f"`{s['reasoning_effort']}`" for s in summaries) + " |"
    sep = "|---|" + "---|" * len(summaries)
    rows = [
        ("Corridas que pasan", lambda s: f"{s['passed_runs']}/{s['runs']} ({s['pass_rate']} %)"),
        ("Latencia p50 / p95", lambda s: f"{s['latency_ms']['p50']} / {s['latency_ms']['p95']} ms"),
        ("Pasos por turno", lambda s: str(s["steps_per_turn"])),
        ("Tokens por turno", lambda s: f"{s['tokens']['per_turn']:,}"),
        ("Costo por turno", lambda s: f"USD {s['cost_usd']['per_turn']}"),
        ("Costo de la corrida", lambda s: f"USD {s['cost_usd']['total']}"),
    ]
    lines = [f"# Evals · {summaries[0]['model']}: reasoning effort", "", head, sep]
    lines += [f"| {name} | " + " | ".join(fn(s) for s in summaries) + " |" for name, fn in rows]
    categories = sorted({c for s in summaries for c in s["categories"]})
    lines += [
        "",
        "| Categoría | " + " | ".join(f"`{s['reasoning_effort']}`" for s in summaries) + " |",
        sep,
    ]
    for cat in categories:
        cells = [
            f"{s['categories'][cat]['pass_rate']} %" if cat in s["categories"] else "—"
            for s in summaries
        ]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"

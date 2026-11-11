"""Evals against the real model (docs/PLAN.md §16, E1). They cost credits: run them by hand.

    python -m scripts.run_evals --check                  # validate the cases, no LLM, no cost
    python -m scripts.run_evals                          # every case x 3, reasoning effort low
    python -m scripts.run_evals --efforts low,medium     # both, plus a comparison table
    python -m scripts.run_evals --only rec_budget_calls,clar_vague --repeat 1

Same code path as POST /api/chat. Each case runs with a fresh eval_* user (deleted at the
end). Writes reports/evals/<date>-<effort>.json and .md (and comparison.md).
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from app.agent.llm.factory import get_llm_provider
from app.config import get_settings
from app.db import get_session_factory
from app.evals.cases import CASES_PATH, load_cases
from app.evals.report import comparison_markdown, markdown, summarize
from app.evals.runner import RunRecord, _resolve, delete_eval_users, run_all
from app.retrieval.embeddings import get_embedder

OUT_DIR = Path("reports/evals")


def _check(cases) -> int:
    """Every product a case refers to exists, without calling the model."""
    with get_session_factory()() as session:
        problems = []
        for case in cases:
            for ref, _ in [*case.setup.cart, *case.setup.purchases]:
                try:
                    _resolve(session, ref)
                except ValueError as error:
                    problems.append(f"{case.id}: {error}")
    for p in problems:
        print(p)
    print(
        f"{len(cases)} cases, {sum(len(c.turns) for c in cases)} turns: "
        f"{'OK' if not problems else f'{len(problems)} problems'}"
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--category", help="only the cases of this category")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument(
        "--efforts", default=None, help="e.g. low,medium (default: LLM_REASONING_EFFORT)"
    )
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--check", action="store_true", help="validate the cases and exit (no LLM)")
    parser.add_argument("--keep-users", action="store_true", help="do not delete the eval_* users")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]
    if args.category:
        cases = [c for c in cases if c.category == args.category]
    if not cases:
        print("No cases selected", file=sys.stderr)
        return 1
    if args.check:
        return _check(cases)

    base = get_settings()
    efforts = args.efforts.split(",") if args.efforts else [base.llm_reasoning_effort]
    factory = get_session_factory()
    embedder = get_embedder(base)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    try:
        for effort in efforts:
            settings = base.model_copy(update={"llm_reasoning_effort": effort})
            llm = get_llm_provider(settings)
            if llm is None:
                print("OPENAI_API_KEY not set", file=sys.stderr)
                return 1
            total = len(cases) * args.repeat
            done: list[RunRecord] = []

            def progress(record: RunRecord, total=total, done=done) -> None:
                done.append(record)
                mark = "ok  " if record.passed else "FAIL"
                print(
                    f"[{len(done):>3}/{total}] {mark} {record.case_id} #{record.repetition}",
                    flush=True,
                )

            model = settings.llm_model
            print(f"== {len(cases)} cases x {args.repeat}, effort={effort}, model={model}")
            runs = asyncio.run(
                run_all(
                    cases, args.repeat, factory, llm, embedder, settings, args.concurrency, progress
                )
            )
            summary = summarize(runs, settings, effort, args.repeat)
            summaries.append(summary)
            name = OUT_DIR / f"{stamp}-{effort}"
            name.with_suffix(".json").write_text(
                json.dumps(
                    {"summary": summary, "runs": [r.as_dict() for r in runs]},
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            name.with_suffix(".md").write_text(markdown(summary), encoding="utf-8")
            print(
                f"-> {summary['passed_runs']}/{summary['runs']} ({summary['pass_rate']} %), "
                f"USD {summary['cost_usd']['total']}, report: {name}.md"
            )
        if len(summaries) > 1:
            path = OUT_DIR / f"{stamp}-comparison.md"
            path.write_text(comparison_markdown(summaries), encoding="utf-8")
            print(f"-> comparison: {path}")
    finally:
        if not args.keep_users:
            deleted = delete_eval_users(factory)
            print(f"Deleted {deleted} eval users")
    return 0


if __name__ == "__main__":
    sys.exit(main())

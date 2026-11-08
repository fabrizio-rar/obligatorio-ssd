"""Catalog rules (pure, no DB or LLM)."""

# Value stored for a spec that has neither value_text nor value_number in the dataset.
# It is shown as "N/D" and never inferred (docs/PLAN.md §2.1).
EMPTY_SPEC_VALUE = "N/D"

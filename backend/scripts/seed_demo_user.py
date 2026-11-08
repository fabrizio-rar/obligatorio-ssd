"""Create the demo user (demo / demo1234) if SEED_DEMO_USER=true. Idempotent.
Runs on startup (entrypoint.sh): docs/PLAN.md §8 step 6."""

import sys

from app.auth.service import DEMO_USERNAME, ensure_demo_user
from app.config import get_settings
from app.db import get_session_factory


def main() -> int:
    if not get_settings().seed_demo_user:
        print("SEED_DEMO_USER=false: skipping demo user.")
        return 0
    with get_session_factory()() as session:
        created = ensure_demo_user(session)
    print(f"Demo user '{DEMO_USERNAME}' {'created' if created else 'already exists'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

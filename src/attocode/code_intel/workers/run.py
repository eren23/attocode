"""Worker entry point: python -m attocode.code_intel.workers.run"""

from __future__ import annotations

import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the ARQ worker."""
    from arq import run_worker

    from attocode.code_intel.workers.settings import WorkerSettings

    # Initialize database engine
    database_url = os.environ.get("DATABASE_URL", "")
    if database_url:
        from attocode.code_intel.db.engine import init_engine

        init_engine(database_url)

    logger.info("Starting ARQ worker...")
    run_worker(WorkerSettings)


if __name__ == "__main__":
    main()

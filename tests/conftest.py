"""Set test-only infrastructure configuration before application imports."""

import os


os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://queue:queue@localhost:5432/queue_test",
)

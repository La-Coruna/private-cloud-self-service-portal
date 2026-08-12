# Backend Database Startup Retry Design

## Goal

Allow the portal backend to survive the temporary MariaDB unavailability that
occurs after a GKE Spot node replacement, then start automatically when the
database becomes reachable without requiring an operator restart.

## Scope

This is a temporary resilience improvement for the current GKE-hosted portal.
It does not attempt to keep the portal reachable while the Spot node or the
ingress controller is unavailable. The later Firebase Hosting, Cloud Run, and
Firestore migration will remove this MariaDB-specific startup dependency.

The change covers only backend startup database availability. It does not add
an init container, change the MariaDB probe, add a Kubernetes startup probe, or
change frontend retry behavior.

## Current Failure

The FastAPI startup handler immediately runs `Base.metadata.create_all()` and
the small inline schema upgrade. After a Spot node replacement, the backend is
often scheduled before the MariaDB PersistentVolume is attached and MariaDB is
accepting connections. The first connection attempt raises SQLAlchemy
`OperationalError`, FastAPI startup exits, and Kubernetes repeatedly restarts
the container.

## Design

Add a focused `wait_for_database()` function in `backend/app/db.py`. It will:

1. Execute `SELECT 1` through the existing SQLAlchemy engine.
2. Catch only SQLAlchemy `OperationalError`, because authentication, DNS, TCP,
   and database-startup failures surface through that exception type.
3. Log the failed attempt and the remaining retry count without logging the
   database URL or credentials.
4. Sleep for a fixed configured delay before the next attempt.
5. Return immediately after the first successful query.
6. Re-raise the final `OperationalError` after the configured attempts are
   exhausted so Kubernetes can restart the container normally.

The FastAPI startup handler will call `wait_for_database()` before running the
existing table creation and schema upgrade. The schema logic remains unchanged
and continues to run only after a successful database readiness query.

## Configuration

Add these settings to `backend/app/config.py`:

- `db_startup_max_attempts: int = 60`
- `db_startup_retry_delay_seconds: float = 5.0`

The GKE backend Deployment will explicitly set:

- `DB_STARTUP_MAX_ATTEMPTS=60`
- `DB_STARTUP_RETRY_DELAY_SECONDS=5`

This gives the database approximately five minutes to become reachable. Local
development receives the same defaults through the settings class, and
`backend/.env.example` will document both variables.

Settings must reject a maximum attempt count below 1 and a negative delay.
A zero-second delay remains valid for tests and exceptional local use.

## Error Handling

Only transient connection failures represented by `OperationalError` are
retried. Programming errors and unexpected exceptions fail immediately so the
retry loop does not hide defects.

When all attempts fail, the original final exception propagates. This preserves
the existing non-zero container exit behavior and makes the root cause visible
in backend logs.

## Testing

Add focused unit tests in `backend/tests/test_db.py` that verify:

- the first successful connection returns without sleeping;
- transient `OperationalError` failures are retried and later success returns;
- the final `OperationalError` is re-raised when attempts are exhausted;
- non-`OperationalError` exceptions are not retried;
- invalid retry settings are rejected by the Pydantic settings model.

Run the complete backend test suite after the focused tests. Validate the GKE
Deployment manifest with a client-side dry run before deployment.

## Acceptance Criteria

- Starting the backend while MariaDB is temporarily unavailable produces
  bounded retry logs instead of an immediate FastAPI startup failure.
- The same backend process completes startup when MariaDB becomes reachable
  within approximately five minutes.
- A database that remains unavailable beyond the retry window still causes a
  clear startup failure and allows Kubernetes to restart the container.
- Existing backend tests pass.
- No credentials appear in retry logs.
- No MariaDB, frontend, or user-project behavior changes in this phase.

## Rollout and Verification

Build and deploy the backend image using the existing GCP deployment workflow.
Observe the backend rollout, confirm `/health` returns HTTP 200 with database
status `ok`, and inspect the backend logs for successful startup.

The controlled Spot recovery test is a separate, explicitly approved
verification step because it intentionally causes temporary service
unavailability. During that test, success means the backend waits for MariaDB
and becomes Ready without manual pod deletion or rollout restart after the new
node is available.

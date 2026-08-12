# Backend Database Startup Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the GKE-hosted FastAPI backend wait up to approximately five minutes for MariaDB during Spot node recovery, then continue startup automatically when the database is ready.

**Architecture:** Add validated retry settings, a focused synchronous database-wait helper around the existing SQLAlchemy engine, and one startup call before the existing schema initialization. Keep the change bounded: final connection failure still aborts startup, unexpected exceptions are never retried, and no MariaDB, frontend, or user-project behavior changes.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Pydantic Settings, `unittest`, Kubernetes Deployment YAML

## Global Constraints

- Retry at most 60 times with a 5-second delay by default, for an approximately five-minute window.
- Retry only SQLAlchemy `OperationalError`; propagate unexpected exceptions immediately.
- Never log the database URL, password, or exception body from a failed connection attempt.
- Re-raise the final `OperationalError` so Kubernetes retains its normal container restart behavior.
- Do not add an init container, MariaDB probe change, Kubernetes startup probe, or frontend retry behavior in this phase.
- Preserve the existing table creation and inline `ingress_host` schema upgrade unchanged after the database becomes reachable.

---

### Task 1: Validated database startup settings

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Create: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `Settings.db_startup_max_attempts: int` with default `60` and minimum `1`.
- Produces: `Settings.db_startup_retry_delay_seconds: float` with default `5.0` and minimum `0`.
- Consumes: Pydantic `Field` validation through `pydantic_settings.BaseSettings`.

- [ ] **Step 1: Write failing settings tests**

Create `backend/tests/test_db.py` with imports for `unittest`, `ValidationError`, and `Settings`. Add tests equivalent to:

```python
class DatabaseStartupSettingsTests(unittest.TestCase):
    def test_database_startup_retry_defaults(self) -> None:
        settings = Settings(_env_file=None)

        self.assertEqual(settings.db_startup_max_attempts, 60)
        self.assertEqual(settings.db_startup_retry_delay_seconds, 5.0)

    def test_database_startup_retry_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, db_startup_max_attempts=0)
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, db_startup_retry_delay_seconds=-0.1)

    def test_database_startup_retry_accepts_zero_delay(self) -> None:
        settings = Settings(
            _env_file=None,
            db_startup_max_attempts=1,
            db_startup_retry_delay_seconds=0,
        )

        self.assertEqual(settings.db_startup_max_attempts, 1)
        self.assertEqual(settings.db_startup_retry_delay_seconds, 0)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run from `backend`:

```powershell
python -m unittest tests.test_db.DatabaseStartupSettingsTests -v
```

Expected: FAIL because both settings fields do not exist.

- [ ] **Step 3: Add validated settings**

Import `Field` from `pydantic` in `backend/app/config.py` and add:

```python
db_startup_max_attempts: int = Field(default=60, ge=1)
db_startup_retry_delay_seconds: float = Field(default=5.0, ge=0)
```

Document the deployment-facing variables in `backend/.env.example`:

```dotenv
DB_STARTUP_MAX_ATTEMPTS=60
DB_STARTUP_RETRY_DELAY_SECONDS=5
```

- [ ] **Step 4: Run the focused tests and verify they pass**

Run from `backend`:

```powershell
python -m unittest tests.test_db.DatabaseStartupSettingsTests -v
```

Expected: 3 tests PASS.

- [ ] **Step 5: Commit the settings change**

```powershell
git add backend/app/config.py backend/.env.example backend/tests/test_db.py
git commit -m "feat: configure backend database startup retries"
```

### Task 2: Bounded database readiness helper

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/tests/test_db.py`

**Interfaces:**
- Produces: `wait_for_database(*, max_attempts: int, retry_delay_seconds: float) -> None`.
- Consumes: module-level SQLAlchemy `engine`, `OperationalError`, `text`, `time.sleep`, and module logger.
- Guarantees: one `SELECT 1` per attempt; no sleep after success or after the final failure.

- [ ] **Step 1: Write failing helper tests**

Extend `backend/tests/test_db.py` using `MagicMock`, `call`, and `patch`. Construct failures with:

```python
def operational_error() -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionRefusedError("unavailable"))
```

Add these cases:

```python
class WaitForDatabaseTests(unittest.TestCase):
    @patch("app.db.time.sleep")
    @patch("app.db.engine.connect")
    def test_returns_immediately_when_database_is_ready(self, connect, sleep) -> None:
        connection = MagicMock()
        connect.return_value.__enter__.return_value = connection

        wait_for_database(max_attempts=3, retry_delay_seconds=5)

        connect.assert_called_once_with()
        connection.execute.assert_called_once()
        sleep.assert_not_called()

    @patch("app.db.time.sleep")
    @patch("app.db.engine.connect")
    def test_retries_operational_error_then_succeeds(self, connect, sleep) -> None:
        success = MagicMock()
        success.__enter__.return_value = MagicMock()
        connect.side_effect = [operational_error(), operational_error(), success]

        wait_for_database(max_attempts=3, retry_delay_seconds=5)

        self.assertEqual(connect.call_count, 3)
        self.assertEqual(sleep.call_args_list, [call(5), call(5)])

    @patch("app.db.time.sleep")
    @patch("app.db.engine.connect")
    def test_raises_final_operational_error_without_final_sleep(self, connect, sleep) -> None:
        failures = [operational_error(), operational_error(), operational_error()]
        connect.side_effect = failures

        with self.assertRaises(OperationalError) as raised:
            wait_for_database(max_attempts=3, retry_delay_seconds=5)

        self.assertIs(raised.exception, failures[-1])
        self.assertEqual(sleep.call_args_list, [call(5), call(5)])

    @patch("app.db.time.sleep")
    @patch("app.db.engine.connect")
    def test_does_not_retry_unexpected_exception(self, connect, sleep) -> None:
        connect.side_effect = RuntimeError("programming defect")

        with self.assertRaisesRegex(RuntimeError, "programming defect"):
            wait_for_database(max_attempts=3, retry_delay_seconds=5)

        connect.assert_called_once_with()
        sleep.assert_not_called()
```

Also use `self.assertLogs("app.db", level="WARNING")` in the transient-failure test and assert the joined log output contains the attempt count but does not contain `unavailable`, `mysql`, or a password-like database URL.

- [ ] **Step 2: Run the helper tests and verify they fail**

Run from `backend`:

```powershell
python -m unittest tests.test_db.WaitForDatabaseTests -v
```

Expected: FAIL because `wait_for_database` does not exist.

- [ ] **Step 3: Implement the minimal helper**

In `backend/app/db.py`, import `logging`, `time`, and `OperationalError`, create `logger = logging.getLogger(__name__)`, and implement:

```python
def wait_for_database(*, max_attempts: int, retry_delay_seconds: float) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
            return
        except OperationalError:
            if attempt == max_attempts:
                logger.error(
                    "Database unavailable after %s startup attempts",
                    max_attempts,
                )
                raise
            logger.warning(
                "Database unavailable during startup attempt %s/%s; "
                "retrying in %.1f seconds",
                attempt,
                max_attempts,
                retry_delay_seconds,
            )
            time.sleep(retry_delay_seconds)
```

Do not include the caught exception in either log call.

- [ ] **Step 4: Run focused and complete backend tests**

Run from `backend`:

```powershell
python -m unittest tests.test_db -v
python -m unittest discover -s tests -v
```

Expected: all focused tests and all existing backend tests PASS.

- [ ] **Step 5: Commit the readiness helper**

```powershell
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: wait for database during backend startup"
```

### Task 3: Wire retry into FastAPI startup and GKE configuration

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_db.py`
- Modify: `infra/gcp/backend-deployment.yaml`

**Interfaces:**
- Consumes: `wait_for_database(max_attempts=settings.db_startup_max_attempts, retry_delay_seconds=settings.db_startup_retry_delay_seconds)`.
- Produces: FastAPI startup ordering of database wait, existing table creation, then existing inline schema upgrade.
- Produces: Deployment environment values `DB_STARTUP_MAX_ATTEMPTS=60` and `DB_STARTUP_RETRY_DELAY_SECONDS=5`.

- [ ] **Step 1: Write a failing startup-order test**

Extend `backend/tests/test_db.py`. Patch `app.main.wait_for_database`, `app.main.Base.metadata.create_all`, `app.main.engine.begin`, and `app.main.inspect`. Use side effects to append operation names to a list, and make the mocked inspector return an existing `ingress_host` column so no ALTER statement is needed. Assert:

```python
self.assertEqual(call_order, ["wait", "create_all", "inspect"])
mock_wait.assert_called_once_with(
    max_attempts=app_settings.db_startup_max_attempts,
    retry_delay_seconds=app_settings.db_startup_retry_delay_seconds,
)
```

Call `create_database_tables()` directly. The test must confirm the existing schema initialization is not entered before the wait helper returns.

- [ ] **Step 2: Run the startup-order test and verify it fails**

Run from `backend` using the exact test class name added in Step 1:

```powershell
python -m unittest tests.test_db.DatabaseStartupIntegrationTests -v
```

Expected: FAIL because `app.main` does not import or call `wait_for_database`.

- [ ] **Step 3: Wire the helper into startup**

Update the `backend/app/main.py` database import to include `wait_for_database`, then make it the first statement in `create_database_tables()`:

```python
wait_for_database(
    max_attempts=settings.db_startup_max_attempts,
    retry_delay_seconds=settings.db_startup_retry_delay_seconds,
)
```

Leave the subsequent `Base.metadata.create_all()`, inspection, and conditional ALTER logic unchanged.

- [ ] **Step 4: Add explicit GKE environment configuration**

In `infra/gcp/backend-deployment.yaml`, add after the existing DB connection variables:

```yaml
- name: DB_STARTUP_MAX_ATTEMPTS
  value: "60"
- name: DB_STARTUP_RETRY_DELAY_SECONDS
  value: "5"
```

- [ ] **Step 5: Run automated verification**

Run:

```powershell
Set-Location backend
python -m unittest tests.test_db.DatabaseStartupIntegrationTests -v
python -m unittest discover -s tests -v
Set-Location ..
kubectl apply --dry-run=client -f infra/gcp/backend-deployment.yaml
git diff --check
```

Expected: all backend tests PASS, the Deployment dry run reports `configured (dry run)`, and `git diff --check` prints nothing.

- [ ] **Step 6: Commit the startup integration**

```powershell
git add backend/app/main.py backend/tests/test_db.py infra/gcp/backend-deployment.yaml
git commit -m "feat: retry database connection before backend startup"
```

### Task 4: Build and non-destructive runtime verification

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: existing backend `Dockerfile` and existing GCP image build/deploy scripts.
- Produces: evidence that the image builds and the currently running service remains healthy after an explicitly approved deployment.

- [ ] **Step 1: Build the backend image locally**

Run from repository root:

```powershell
docker build -t portal-backend:db-startup-retry ./backend
```

Expected: Docker build completes successfully.

- [ ] **Step 2: Re-run repository verification immediately before completion**

```powershell
Set-Location backend
python -m unittest discover -s tests -v
Set-Location ..
kubectl apply --dry-run=client -f infra/gcp/backend-deployment.yaml
git status --short
```

Expected: all tests PASS, dry run succeeds, and only intentional or pre-existing files appear in status.

- [ ] **Step 3: Stop before cloud deployment unless separately authorized**

Building and pushing to Artifact Registry, updating the live Deployment, or deliberately triggering a Spot node replacement changes external state and can interrupt the portal. Report the verified local implementation and ask for explicit deployment authorization before running the existing GCP build-and-deploy workflow.

- [ ] **Step 4: After authorized deployment, verify normal startup**

Use the existing image build/push and deployment scripts with a unique tag. Then run:

```powershell
kubectl rollout status deployment/portal-backend -n portal-system --timeout=360s
kubectl logs -n portal-system deployment/portal-backend --tail=200
curl.exe --fail --show-error --max-time 20 http://portal.la-coruna.xyz/health
```

Expected: rollout succeeds, startup completes, and `/health` returns HTTP 200 with database status `ok`.

- [ ] **Step 5: Treat controlled Spot recovery as a separate approval gate**

Do not delete, drain, resize, or otherwise interrupt the active Spot node during ordinary implementation verification. After explicit authorization, perform one controlled recovery test and confirm the backend reaches Ready without manual pod deletion or rollout restart after MariaDB becomes available.

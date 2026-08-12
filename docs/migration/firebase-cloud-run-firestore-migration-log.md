# Firebase, Cloud Run, and Firestore migration log

All timestamps use Korea Standard Time (UTC+09:00). This record is intentionally sanitized: it contains no credentials, tokens, numeric cloud project identifiers, password output, public endpoints, or workstation paths. Unless an entry explicitly says otherwise, it records repository work and local verification, not a cloud deployment.

## Chronology

| Time | Evidence | Verified result |
| --- | --- | --- |
| 2026-08-12 14:29 | Commit `596016d` | Recorded the design for bounded database startup retry after the Spot/MariaDB recovery incident. |
| 2026-08-12 14:37 | Commit `8aca199` | Recorded the implementation plan for the database startup retry. |
| 2026-08-12 14:54 | Commit `d31a676` | Added a database readiness wait before schema initialization. The deployment configuration allowed 60 attempts with a five-second delay. This mitigated recovery ordering but did not remove the portal's dependency on the Spot node lifecycle. |
| 2026-08-12 16:42 | Commit `53199fd` | Approved the serverless migration design: Firebase Hosting for the SPA, Cloud Run for FastAPI, Firestore for portal records, and the GKE API for user workloads. |
| 2026-08-12 16:55 | Commit `490f688` | Added the phased application, infrastructure, and cutover plan, including parallel operation and rollback gates. |
| 2026-08-12 17:41–20:41 | Commits `42795af`, `d0b9515`, `e00686a`, `e789c81` | Separated the domain/repository contract, added Firestore persistence and invariants, and changed FastAPI persistence from MariaDB to Firestore. |
| 2026-08-12 22:01 | Base commit `5c21f35` | Application work through stale platform-status protection was present before the local emulator task began. |
| 2026-08-12 22:11 | `npm test` | Frontend baseline passed: 4 files and 24 tests. |
| 2026-08-12 22:14 | Emulator test without `FIRESTORE_EMULATOR_HOST` | Both integration cases skipped with the documented emulator-host reason; no other skip condition was used. |
| 2026-08-12 22:16 | First `firebase emulators:exec` run | RED: the project/audit round trip passed, while one of four concurrent claims exhausted the client's default five transaction attempts. Sanitized error: Firestore returned `409 Transaction lock timeout`, surfaced after five attempts. No cloud service was contacted or changed. |
| 2026-08-12 22:22 | Focused transaction-attempt unit test | First RED expected `[10, 10]` for claim and release but observed `[5, 5]`; the first configured emulator run then passed with ten attempts. |
| 2026-08-12 22:26 | Configured `firebase emulators:exec` run | GREEN: 2 integration tests passed in 13.140 seconds. Four concurrent requests produced exactly three stored projects and one `DemoCapacityExceeded`; a fresh repository returned the complete project and two audit logs in chronological order. The emulator listened on `127.0.0.1:8085`. |
| 2026-08-12 22:30 | Fresh repeated emulator run | RED: the same four-thread case intermittently exhausted the ten-attempt budget with the same sanitized lock-timeout error. A second focused RED expected `[20, 20]` but observed `[10, 10]`; claim and release were then raised to a still-finite twenty attempts. Repeated emulator verification is required before completion. |
| 2026-08-12 22:34 | Three fresh twenty-attempt emulator runs | GREEN: all three independent emulator startups passed both required cases. Durations were 23.402, 37.520, and 11.240 seconds; each produced three claims plus one capacity rejection and a passing fresh-repository round trip. |

## Current local workflow

- `REPOSITORY_BACKEND=memory` is the fast, database-free development path.
- `REPOSITORY_BACKEND=firestore`, `FIRESTORE_PROJECT_ID=serverless-portal-local`, and `FIRESTORE_EMULATOR_HOST=127.0.0.1:8085` select local Firestore persistence.
- `firebase emulators:exec --only firestore "backend\.venv\Scripts\python.exe -m unittest backend.tests.integration.test_firestore_emulator -v"` starts the emulator and supplies its host to the real-client tests.
- Firebase Hosting is configured to publish `frontend/dist` with SPA fallback.
- No permissive production client rules were added. The deployed design accesses Firestore from the server with application credentials; this task performed no deployment and changed no Firebase or GCP resource.

## Rollback record

The legacy GKE portal manifests, MariaDB workload, and persistent storage remain rollback assets until a separately approved cutover completes its observation window. The planned cutover keeps old and new paths available in parallel, records the exact pre-cutover DNS value privately, and restores that value if acceptance fails. Legacy database storage must not be deleted merely because the serverless local workflow passes. Existing demo rows are intentionally not migrated; the Firestore target begins empty.

## Remaining gates

Local application verification does not prove cloud IAM, GKE DNS endpoint access, Cloud Run behavior, Firebase Hosting rewrites to a deployed backend, custom-domain TLS, or production rollback. Those belong to later reviewed phases and require explicit authorization.

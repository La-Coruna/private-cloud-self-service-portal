# Decoupling a self-service portal from Spot-node recovery

_Draft based on verified repository history and local emulator results as of 2026-08-12. Cloud deployment and cutover results are deliberately not claimed._

## The incident exposed a shared failure domain

The first public-demo architecture placed the React frontend, FastAPI backend, and MariaDB database alongside user workloads on a GKE Standard Spot node. When that node was replaced, the platform control plane and the workloads it managed became unavailable together. MariaDB did not become ready before the backend's initial database connection, so FastAPI startup failed even after Kubernetes began reconstructing the Pods.

The immediate mitigation was bounded database startup retry. Commit `d31a676` made the backend wait for database readiness before schema initialization; the deployment allowed 60 attempts separated by five seconds. That addressed startup ordering and made automatic recovery more likely. It did not address the deeper design problem: the portal, its durable state, and the user compute pool still shared the same Spot lifecycle.

## The approved target separates the control plane

The migration design in commits `53199fd` and `490f688` moves the React build to Firebase Hosting, runs FastAPI on Cloud Run, and stores project and audit records in Firestore. Cloud Run calls the GKE DNS-based API endpoint using its service identity and narrowly scoped Kubernetes RBAC. GKE continues to run user project workloads and the shared ingress controller, but a Spot replacement no longer needs to erase access to the portal's saved state.

This is an architecture target, not a deployment claim. The work described here configured and tested the application locally. It did not enable APIs, create cloud databases, change IAM or DNS, deploy a service, or alter a Firebase/GCP resource.

## Two state machines are clearer than one overloaded status

Project lifecycle remains durable in Firestore with six values:

`REQUESTED → PROVISIONING → RUNNING`, with `FAILED`, `DELETING`, and `DELETED` representing workload outcomes and cleanup.

Platform availability is a separate live observation with three values:

- `AVAILABLE`: the Kubernetes API is reachable and schedulable capacity is ready.
- `RECOVERING`: the API is reachable but ready capacity is not yet available.
- `UNAVAILABLE`: authentication, network, or API access failed.

That separation matters during a Spot event. A previously saved `RUNNING` project does not become `FAILED` merely because the platform is temporarily recovering. Read-only Firestore-backed project and audit views remain meaningful, while creation and live Kubernetes reads can be blocked with an explicit availability reason.

## A real emulator found a contention edge case

Unit tests had already verified the Firestore mapping and transaction contract with a fake client. The new integration test used the real Firestore emulator and four threads against a demo capacity of three. The first run was intentionally red: the project/audit round trip passed, but one capacity transaction exhausted the Firestore client's default five attempts after a sanitized `409 Transaction lock timeout`.

A focused unit test first proved that both capacity claim and release still requested five attempts. Ten attempts passed one emulator run but exhausted intermittently when the identical four-thread check was repeated. A second red/green unit cycle therefore set a still-finite twenty-attempt limit for those two shared-document transactions. Three fresh emulator startups then passed: exactly three claims succeeded, exactly one raised `DemoCapacityExceeded`, and a new repository instance reconstructed the complete project plus two audit records in chronological order each time. No production data or service was touched by this workflow.

The lesson is modest but useful: an atomic transaction is necessary for a global demo limit, yet the client retry budget is also part of the behavior when four requests contend for one counter document. The finite limit improves this small public-demo workload without turning retries into an unbounded failure mode.

## Local development no longer requires MariaDB

For fast development, `REPOSITORY_BACKEND=memory` keeps unit work self-contained. For persistence integration, the documented Firebase command starts Firestore on `127.0.0.1:8085` and runs the real-client suite with the emulator host injected. Firebase Hosting points at `frontend/dist` for the SPA build. No permissive production client rules were added because the design keeps Firestore access behind the server-side FastAPI process.

MariaDB documentation is retained only as legacy architecture and rollback history. It is not a required dependency for the serverless application path.

## The application checkpoint caught a Cloud Run port mismatch

The final local checkpoint deliberately rebuilt the backend image and launched it with the same port contract Cloud Run supplies. One preliminary backend test command failed before reaching any tests because it was invoked from the repository root while the application package is rooted under `backend`. Running the suite from the correct working directory passed all 82 tests, which separated a command-context error from an application defect without changing source code.

The container check found a real defect. Although the environment contained `PORT=8080` and Docker published host port 8080 to container port 8080, the image command still forced Uvicorn to listen on 8000. The first `/health` call therefore returned an empty response, and the container log exposed the mismatch directly. Commit `99c460c` changed only the container contract: the image now exposes 8080 and starts Uvicorn with `${PORT:-8080}`.

After rebuilding `portal-backend:firestore-local`, the log showed Uvicorn listening on `0.0.0.0:8080` and `/health` returned HTTP 200. The aggregate payload was `degraded`, not `ok`, for an intentional reason: the memory repository was healthy, while GKE was `UNAVAILABLE` because the isolated container had no local kubeconfig. That result demonstrated the designed separation between durable portal health and live platform availability. A fresh post-fix run then passed 82 backend tests, backend compilation, 24 frontend tests, lint, and the production frontend build. This remained entirely local; no cloud API, IAM binding, DNS record, database, or deployment was changed.

## Rollback remains a first-class phase

The cutover plan does not treat a green local emulator as permission to destroy the old platform. The legacy GKE portal, MariaDB workload, and persistent storage remain available during a parallel observation period. Before changing a custom domain, operators record the current DNS target in a private operational record. If acceptance fails, traffic returns to that recorded target and the old health path is rechecked.

Removal is deliberately split into later approvals. Stateless legacy portal components can be considered only after the observation gate; MariaDB storage is a separate decision because deleting it removes the easiest data-level rollback. The demo Firestore database begins empty, so there is no hidden promise to migrate legacy demo rows.

## What is verified, and what is still ahead

Verified locally: frontend unit tests and production build, memory-backed backend behavior, Firestore transaction retry configuration, concurrent demo-capacity enforcement, persistence across repository reconstruction, audit ordering, Firebase emulator/Hosting configuration, and the backend container's `$PORT=8080` health contract.

Still gated: deployed Cloud Run runtime and IAM behavior, Firestore location and production access, GKE DNS endpoint authentication, Firebase-to-Cloud-Run routing, custom-domain TLS, 24-hour observation, cleanup, and measured cost results. Those facts should be added only after their respective commands have run and their evidence has been recorded.

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
| 2026-08-12 22:49 | Python 3.12.10, `python -m unittest discover` | The first repository-root invocation produced 13 import errors because `app` was not on the import path. This was an invocation error, not an application failure: rerunning from the `backend` working directory passed all 82 tests in 0.187 seconds, and `python -m compileall app` succeeded. No source change was made for this result. |
| 2026-08-12 22:51 | Node.js v24.18.0, npm 11.16.0 | Frontend verification passed 4 files and 24 tests in 2.99 seconds; `npm run lint` exited zero; `npm run build` transformed 136 modules and produced `frontend/dist/index.html`. |
| 2026-08-12 22:53 | Docker 29.6.1 (build 8900f1d), image `portal-backend:firestore-local` | RED: the image built, but a container started with `PORT=8080` and host mapping `8080:8080` returned an empty response at `/health`. Container evidence showed the environment contained `PORT=8080` while the image command still forced Uvicorn to port 8000. |
| 2026-08-12 22:55 | Commit `99c460c`, Firebase CLI 15.24.0 | GREEN: the Dockerfile now exposes 8080 and expands `${PORT:-8080}` in the Uvicorn command. The rebuilt container listened on `0.0.0.0:8080`; `/health` returned HTTP 200. With the memory repository and no kubeconfig mounted, the response was correctly separated as Firestore `ok`, GKE `UNAVAILABLE`, and aggregate status `degraded`. The one-off container was stopped and removed. |
| 2026-08-12 22:56 | Fresh post-fix application verification | Backend: 82 tests passed in 0.165 seconds and compilation succeeded. Frontend: 4 files and 24 tests passed in 3.00 seconds, lint exited zero, and the production build again produced `dist/index.html`. |
| 2026-08-13 18:49 | Serverless infrastructure Task 1 | Captured the sanitized pre-change inventory, enabled exactly the seven approved APIs, and reran the idempotent script. Both executions exited zero; an independent query returned all seven names with no missing or unexpected service. No Firebase registration, Firestore database, Cloud Run service, IAM identity, GKE setting, workload, ingress, or DNS record was created or changed. |
| 2026-08-13 19:01 | Serverless infrastructure Task 2 | Created the `(default)` Firestore database in `asia-northeast3` using Firestore Native mode. An independent describe confirmed the immutable location and type, and a second script run returned `no-op`. No Firebase registration, IAM, GKE, DNS, or deployment change was made. |
| 2026-08-14 13:08 | Serverless infrastructure Task 4 | Enabled external access to the existing GKE DNS control-plane endpoint with the one approved cluster update. Independent verification retained both IP endpoints, kept Kubernetes tokens and certificates via DNS disabled, and found no authorized-network change. A DNS-endpoint `kubectl get nodes` returned one of one nodes Ready, the original context was preserved, and the idempotent rerun returned `no-op`. |

## Infrastructure Task 1 inventory and API enablement

The pre-change checks used the expected GCP project and the existing `portal-demo-standard` Kubernetes context. The active gcloud and Firebase identities were compared for equality without recording either identity; they matched after reauthentication. Firebase CLI 15.24.0 was invoked with the already-installed Node.js 20 runtime because Node.js 24 intermittently terminated the Windows CLI with a libuv assertion after otherwise successful commands.

Before API enablement:

- Three of the seven planned services were enabled: Artifact Registry, GKE, and IAM.
- Cloud Run, Firestore, Firebase Management, and Firebase Hosting APIs were disabled. Consequently, the first Cloud Run and Firestore inventory calls could not query those services. Immediately after API enablement, both inventories completed and contained zero Cloud Run services and zero Firestore databases; enabling the APIs did not provision either resource.
- The GCP project was accessible, but it was not yet present in the authenticated Firebase project list. This is the expected pre-registration state; `firebase projects:addfirebase` was deliberately not run in this task.
- The planned `portal-cloud-run` service account did not exist.
- The GKE cluster was `RUNNING`. Its DNS endpoint existed but did not allow external DNS traffic, while its IP endpoint remained available for rollback.
- The cluster contained 43 Deployments, StatefulSets, and DaemonSets. The existing `portal-system` workloads were `portal-backend`, `portal-frontend`, and `portal-mariadb`.
- Two ingresses had two assigned addresses. The public portal hostname returned one A record, and that answer matched an existing ingress address. The address itself is intentionally omitted from this record.

`infra/gcp/serverless/01-enable-serverless-apis.ps1` enabled and verified exactly:

- `run.googleapis.com`
- `firestore.googleapis.com`
- `firebase.googleapis.com`
- `firebasehosting.googleapis.com`
- `artifactregistry.googleapis.com`
- `container.googleapis.com`
- `iam.googleapis.com`

The first execution exited zero and printed all seven service names. A second execution also exited zero and printed the identical set. A separate enabled-service query at `2026-08-13 18:49:01 KST` reported seven matches, zero missing services, and zero unexpected services.

## Infrastructure Task 2 Firestore provisioning

The preflight confirmed that the active gcloud account was the explicitly approved deployment account and that the active, accessible project was the expected project. The comparison result was recorded without printing or storing the account identity. A fresh description showed that `(default)` did not exist before provisioning.

The decision function was exercised with absent, Seoul Native, wrong-location, and wrong-type fixtures. Script contract tests also verified PowerShell syntax, exactly one create call for an absent database, no create call on the second run, and a hard stop before mutation for an incompatible existing database. The first live attempt stopped before creation because Windows PowerShell promoted the expected `describe` NOT_FOUND output to an error record. A focused regression test reproduced that boundary behavior; the script now temporarily inspects the native command exit code for that describe call and restores strict error handling immediately afterward.

At `2026-08-13 19:01 KST`, the script created the default database once with:

- location: `asia-northeast3`
- type: `FIRESTORE_NATIVE`
- database name: `(default)`

An independent read returned the same location and type. The immediate second execution exited zero with `result=no-op`, proving idempotency against the live database. Firestore database location is immutable, so the script refuses to continue if an existing default database is outside Seoul or is not Native mode. This task did not register the project with Firebase, create or modify IAM identities, alter GKE or DNS, or deploy an application.

## Infrastructure Task 3 Cloud Run identity and least-privilege access

Before mutation, the proposed permanent grants were presented for a separate security checkpoint. The user explicitly approved only `roles/datastore.user`, `roles/container.viewer`, and `roles/logging.logWriter` for the dedicated Cloud Run runtime identity, plus cluster-scoped `get`, `list`, `watch`, `create`, and `delete` on namespaces, resource quotas, services, pods, events, Deployments, and Ingresses. The approval expressly excluded secrets, Kubernetes RBAC, nodes, pod exec, and pod logs. No broader role was inferred from the approval.

The identity configuration created the dedicated service account and granted the three approved, unconditional project roles. An independent live-policy query found exactly those three roles and no conditional or unexpected binding. The idempotency run returned `result=no-op` with the same exact role set.

The approved manifest created one ClusterRole and one ClusterRoleBinding for the IAM service-account identity represented as a Kubernetes `User`. A client dry run and idempotent live reapply reported both objects unchanged. A separate structural read found exactly three rules, the seven approved resources, the five approved verbs, one subject, and the expected role reference.

An early check used `pods/exec` as if it were a resource name and produced a misleading `yes`; that form is not valid proof of the exec subresource. Before completion, the contract was corrected to use `kubectl auth can-i create pods --subresource=exec`, which returned `no`. The corresponding `get pods --subresource=log` check also returned `no`. Fresh checks returned `yes` for creating Deployments and deleting namespaces, and `no` for reading secrets, creating ClusterRoles, and updating nodes. The repository contract now uses this explicit subresource syntax.

This task did not change GKE endpoint settings, deploy Cloud Run or Firebase Hosting, modify DNS, or remove any rollback resource.

## Infrastructure Task 4 GKE DNS control-plane endpoint

The preflight matched the approved new deployment account without recording its identity, and matched project `private-cloud-portal-demo-2`, cluster `portal-demo-standard`, zone `asia-northeast3-a`, and cluster status `RUNNING`. The script rejects any other account, project, cluster, or zone before mutation. It also validates the exact known property set for the DNS and IP endpoint configurations so that a missing or newly introduced endpoint flag cannot be silently treated as false.

The complete sanitized endpoint flags immediately before and after the change were:

| Control-plane property | Before | After |
| --- | --- | --- |
| DNS endpoint present | true | true |
| External DNS traffic allowed | false | true |
| Kubernetes tokens via DNS | false | false |
| Kubernetes certificates via DNS | false | false |
| IP endpoints enabled | true | true |
| Public IP endpoint enabled | true | true |
| Public IP endpoint present | true | true |
| Private IP endpoint present | true | true |
| Authorized networks configured | false | false |

The only mutation command issued by the script was:

```text
gcloud container clusters update portal-demo-standard --zone asia-northeast3-a --project private-cloud-portal-demo-2 --enable-dns-access
```

No IP-access disable flag, authorized-network flag, or token/certificate-via-DNS flag was passed. A separate post-update description reproduced the after-state above. The immediate second script execution returned `result=no-op` and emitted identical before/after flags, demonstrating live idempotency.

For the bounded connectivity check, the previous kubectl current context was recorded and the DNS credentials were generated only in a temporary kubeconfig. `gcloud container clusters get-credentials` used the approved project, cluster, zone, and `--dns-endpoint`; the only Kubernetes operation was read-only `kubectl get nodes`. It returned one node and one Ready node. The temporary kubeconfig was deleted in `finally`, the original kubeconfig environment was restored, and the original current context compared equal afterward. No credential material or endpoint address was written to this log or retained outside the normal local configuration.

PowerShell syntax and mocked command-contract tests passed. The contract accepts only the exact update command above, proves a disabled endpoint is updated once, proves a repeat is a no-op, and stops before update for the previous account, token-via-DNS enablement, public-IP disablement, or an unexpected cluster zone.

This task did not deploy Cloud Run or Firebase Hosting, modify Kubernetes workloads or RBAC, change application DNS records, alter authorized networks, or remove any GKE rollback endpoint.

## Current local workflow

- `REPOSITORY_BACKEND=memory` is the fast, database-free development path.
- `REPOSITORY_BACKEND=firestore`, `FIRESTORE_PROJECT_ID=serverless-portal-local`, and `FIRESTORE_EMULATOR_HOST=127.0.0.1:8085` select local Firestore persistence.
- `firebase emulators:exec --only firestore "backend\.venv\Scripts\python.exe -m unittest backend.tests.integration.test_firestore_emulator -v"` starts the emulator and supplies its host to the real-client tests.
- Firebase Hosting is configured to publish `frontend/dist` with SPA fallback.
- `docker build -t portal-backend:firestore-local backend` produces the local Cloud Run candidate. The verified launch contract passes `PORT=8080`, `REPOSITORY_BACKEND=memory`, and `KUBE_AUTH_MODE=local`; local `/health` returned HTTP 200 on port 8080.
- No permissive production client rules were added. The deployed design accesses Firestore from the server with application credentials; this task performed no deployment and changed no Firebase or GCP resource.

## Rollback record

The legacy GKE portal manifests, MariaDB workload, and persistent storage remain rollback assets until a separately approved cutover completes its observation window. The planned cutover keeps old and new paths available in parallel, records the exact pre-cutover DNS value privately, and restores that value if acceptance fails. Legacy database storage must not be deleted merely because the serverless local workflow passes. Existing demo rows are intentionally not migrated; the Firestore target begins empty.

## Remaining gates

Local application verification now covers the container's `$PORT` contract, but it does not prove deployed Cloud Run runtime or IAM behavior, GKE DNS endpoint access, Firebase Hosting rewrites to a deployed backend, custom-domain TLS, or production rollback. Those belong to later reviewed phases and require explicit authorization.

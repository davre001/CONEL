# FORGE — Backend Implementation Specification

## Design goals

Build a **bounded, auditable, resumable** repair workflow, not an unconstrained shell agent. A real LLM generates a real patch; a real CreateOS sandbox executes real independent tests; only a human-approved patch can modify the controlled demo target.

## Runtime architecture

**Next.js API** handles validation, auth, reads, and enqueuing. **Node worker** handles health checks and long-running repair orchestration. **Postgres** is the durable source of truth for incidents, runs, events, approvals, and audit logs. Use a Postgres-backed job queue with lease/heartbeat or a durable job service; do not run multi-minute sandboxes inside short-lived HTTP handlers.

```text
Health probe → Incident upsert → Repair job → LLM diagnosis
→ LLM patch → path validation → CreateOS sandbox
→ baseline tests → apply patch in sandbox → independent tests
→ evidence + approval request → approved demo apply
→ external health probe + Stripe test verification → recovered
```

## State machine

- `detected` → `diagnosing` → `patching` → `testing` → `awaiting_approval` → `applying` → `verifying` → `recovered`.
- Terminal/exception states: `repair_failed`, `verification_failed`, `timed_out`, `cancelled`, `rolled_back`.
- Persist each transition and a sequenced event in the same database transaction.
- `repair_failed` may be retried by creating a **new** run; never overwrite prior evidence.
- `recovered` requires an actual post-apply probe; a green test badge is insufficient.

## Contracts

```ts
type IncidentStatus =
  | 'detected' | 'diagnosing' | 'patching' | 'testing'
  | 'awaiting_approval' | 'applying' | 'verifying' | 'recovered'
  | 'repair_failed' | 'verification_failed' | 'timed_out'
  | 'cancelled' | 'rolled_back';

type PatchProposal = {
  summary: string;
  rootCause: string;
  unifiedDiff: string;
  changedPaths: string[];
  reasoningEvidence: string[];
};

type VerificationResult = {
  baselineFailed: boolean;
  patchedExitCode: number;
  independentTestsPassed: boolean;
  regressionTestsPassed: boolean;
  stdout: string;
  stderr: string;
  durationMs: number;
};
```

## Routes

| Method | Route | Behavior |
|---|---|---|
| GET | `/api/incidents` | Paginated, filters by status/severity |
| GET | `/api/incidents/:id` | Incident + run + patch + test evidence |
| POST | `/api/incidents/:id/repair` | Authenticate; idempotently enqueue; 202 |
| GET | `/api/incidents/:id/events` | Authenticated SSE; resume with last event id |
| POST | `/api/incidents/:id/approve` | Auth + explicit patch id + optimistic status check |
| POST | `/api/demo/inject-failure` | Demo admin only; never enabled for arbitrary apps |
| POST | `/api/demo/reset` | Demo admin only; restore known-good fixture |
| GET | `/api/health` | FORGE service liveness, not storefront health |

Use Zod schemas, request IDs, rate limits, CSRF protection where relevant, and structured errors (`code`, `message`, `requestId`). The approval action requires authenticated user identity, audit log, and idempotency key.

## Orchestrator pseudocode

```ts
async function runRepair(incidentId: string) {
  const run = await createRepairRun(incidentId);
  const snapshot = await loadAllowlistedFixtureSnapshot(incidentId);
  const diagnosis = await llm.diagnose({ error: snapshot.error, files: snapshot.files });
  await emit(run, 'diagnosis.completed', diagnosis);

  for (let attempt = 1; attempt <= 2; attempt++) {
    const proposal = await llm.generatePatch({ diagnosis, snapshot, attempt });
    validateUnifiedDiff(proposal.unifiedDiff, snapshot.allowedPaths);
    const verification = await sandboxRunner.verify({ snapshot, proposal });
    await persistEvidence(run, proposal, verification);

    if (verification.baselineFailed && verification.independentTestsPassed &&
        verification.regressionTestsPassed && verification.patchedExitCode === 0) {
      await transitionToAwaitingApproval(run, proposal);
      return;
    }
  }
  await markRepairFailed(run);
}
```

The agent cannot author or edit the independent acceptance tests. LLM output must be parsed and validated; malformed patches or changes outside allowlisted paths are rejected.

## CreateOS runner

```ts
import { createClient } from '@nodeops-createos/sandbox';

const client = createClient(); // reads CREATEOS_SANDBOX_API_KEY

export async function executeFixtureTest(testScript: string) {
  const sandbox = await client.createSandbox({
    shape: 's-1vcpu-1gb',
    rootfs: 'devbox:1',
  });
  try {
    // Production implementation uploads a clean fixture snapshot here.
    await sandbox.files.upload('/root/test.sh', testScript);
    const { result, exec_ms } = await sandbox.runCommand(
      'sh', ['/root/test.sh'], { timeoutMs: 60_000 }
    );
    return { stdout: result.stdout, stderr: result.stderr,
             exitCode: result.exit_code, durationMs: exec_ms };
  } finally {
    await sandbox.destroy();
  }
}
```

This is an **SDK integration example**, not a full repair runner. The real implementation must upload the full fixture, check baseline failure, apply the validated diff inside the sandbox, run independent tests, capture logs, and clean up in `finally`. Use `sandbox.streamCommand` when streaming terminal output. Use a sandbox image with the fixture's required runtime installed, confirmed via SDK catalog calls. Sandbox resources incur usage; default to **one sandbox and sequential attempts**. Parallel candidates are a stretch goal and may require higher account concurrency limits.

## Demo fixture

Seed a checkout handler with a reproducible null/undefined dereference, plus an independent test that asserts the correct response contract. Ensure the original fixture fails and the known-good fixture passes **before** involving the LLM. Store checksums of original source and acceptance tests. Generate a new isolated workspace per run.

## Approval and apply

For MVP, apply only to a versioned **demo application snapshot** (or a demo Git branch). Require patch hash to match verified artifact. Re-run tests after apply; then probe the actual running endpoint. If a post-apply probe fails, restore previous version and set `rolled_back` or `verification_failed`. No production deployment or arbitrary repository write access.

## Database and durability

Use Drizzle migrations. Unique `(incident_id, run_attempt)` and unique `(incident_id, seq)`; index incident status and creation time. Queue workers must claim jobs atomically, renew leases, and safely resume/retry after crash. Store logs with secret redaction and size caps. Keep full patches only in access-controlled storage.

## Security and resource budgets

- Allowlist fixture paths; reject symlinks, traversal, binaries, lockfile edits, and executable deployment scripts for MVP.
- Never mount host filesystem, cloud credentials, DB secrets, Stripe keys, or the LLM key inside repair sandboxes.
- Restrict egress to none/required package registries where supported; do not assume open egress is safe.
- Per-run command timeout, max 2 repair attempts, log-size cap, maximum file count and patch size, budget ceiling, concurrency cap.
- Only execute vetted fixed test commands, not arbitrary LLM-generated shell commands.
- Require explicit approval for any demo-target mutation; never expose provisioning commands as an unrestricted agent tool.
- Persist a tamper-evident audit trail of who approved what, when, and against which patch hash.

## Test strategy

1. Unit: schema validation, diff path allowlist, status transitions, ranking, idempotency.
2. Integration: CreateOS create/upload/exec/destroy, baseline red and patched green.
3. E2E: failure injection → incident → generated patch → approval → healthy endpoint.
4. Negative: bad patch, failing tests, missing API key, CreateOS timeout, approval race, failed post-apply probe, worker restart.
5. Payment: Stripe test-mode success and failure paths; no live keys or real charges.

## Delivery priorities

**P0:** fixture + health check + incident DB + one real LLM patch + one real sandbox test + human approval + successful re-probe. **P1:** SSE logs, rich diff, Stripe test checkout, deployment. **P2:** competing repair candidates, rollback automation, richer metrics.

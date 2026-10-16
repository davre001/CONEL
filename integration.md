# FORGE — Integration Guide

## Integration map

| Service | What FORGE uses it for | Required for MVP? |
|---|---|---|
| **CreateOS Sandbox** | Run AI-generated patches and independent tests in isolated Linux environments | Yes |
| **Stripe Projects** | Provision/manage Neon database and Vercel project from CLI, sync environment credentials, share stack for hackathon | Yes |
| **Neon** | Persist incidents, events, patches, audit logs | Yes (or temporary local DB during early dev) |
| **LLM API** | Diagnose source errors and generate bounded unified diffs | Yes |
| **Vercel** | Host dashboard and short-lived API routes | Target deployment |
| **Stripe Payments** | Verify recovery of a simulated checkout using test-mode transactions | Recommended demo extension |

**Important:** Stripe Projects and Stripe Payments are separate products. Stripe Projects is not a payment API. The Stripe Payments integration adds a compelling revenue-recovery demo but is not a substitute for using Stripe Projects.

## A. Stripe Projects — provision infrastructure

### Install and initialize

```bash
npm install -g @stripe/cli@latest
stripe plugin install projects
stripe projects --help
stripe projects init forge
stripe projects catalog
```

Authenticate interactively when prompted. Verify the exact provider slugs with `stripe projects catalog` before using them. Supported documented examples:

```bash
stripe projects add neon/postgres
stripe projects add vercel/project
stripe projects env --pull
stripe projects spend
```

Projects may create `.projects/state.json`, `.projects/state.local.json`, `.agents/skills`, `AGENTS.md`, `CLAUDE.md`, and `.env`. Review generated files. Keep local state and credentials private; commit only safe metadata. Stripe Projects provisions infrastructure at setup time; **FORGE does not automatically create replacement paid services during repairs** in the MVP.

### Hackathon submission evidence

```bash
stripe whoami
stripe projects share
```

Save the share link, deployed URL, and public repository URL. Follow the event organizer's actual submission instructions and use the event code only if one is provided. Do not assume generic leaderboard instructions supersede the event rules.

## B. CreateOS Sandbox — real code execution

### Install and authenticate

```bash
pnpm add @nodeops-createos/sandbox
```

Set `CREATEOS_SANDBOX_API_KEY` in the **server/worker** environment only. Never use `NEXT_PUBLIC_` for this key. Confirm account access and available machine shapes before running jobs.

### Connectivity smoke test

```ts
import { createClient } from '@nodeops-createos/sandbox';

const client = createClient();
const sandbox = await client.createSandbox({
  shape: 's-1vcpu-1gb',
  rootfs: 'devbox:1',
});
try {
  const { result } = await sandbox.runCommand('node', ['--version']);
  if (result.exit_code !== 0) throw new Error(result.stderr);
  console.log(result.stdout);
} finally {
  await sandbox.destroy();
}
```

The real repair integration:

1. Create sandbox using an available shape and compatible root filesystem.
2. Upload **clean fixture** and immutable acceptance tests with `sandbox.files.upload`.
3. Run baseline tests; assert they fail for the seeded bug.
4. Apply a validated patch to the allowlisted source files **inside the sandbox**.
5. Run independent tests and regression checks with `runCommand` or `streamCommand`.
6. Record exit codes, stdout/stderr, durations, and sandbox id; redact secrets.
7. Destroy sandbox in `finally`, including error/timeout paths.

Use a separate sandbox for each candidate if parallel repair is added later; account concurrency limits may prevent this on free tiers.

## C. LLM provider — diagnosis and patching

Expose a narrow `LLMProvider` interface:

```ts
interface LLMProvider {
  diagnose(input: { error: string; files: Record<string, string> }):
    Promise<{ rootCause: string; evidence: string[] }>;
  proposePatch(input: { rootCause: string; files: Record<string, string> }):
    Promise<{ unifiedDiff: string; changedPaths: string[]; summary: string }>;
}
```

Provide only the fixture files and sanitized error logs. Validate model output with Zod. The model must not see secret environment variables or edit acceptance tests. Limit attempts and tokens; persist only useful, redacted outputs.

## D. Neon database

After Stripe Projects provisions Neon, identify the actual database URL variable in the generated `.env`; map it to `DATABASE_URL` for Drizzle without committing the value. Run migrations for `incidents`, `repair_runs`, `patches`, `test_results`, `incident_events`, and `audit_logs`. Database credentials belong only in backend/worker environments.

## E. Stripe Payments — test checkout recovery

**Optional but highly recommended for demo impact.** Use Stripe test mode only. The storefront backend creates a Checkout Session or PaymentIntent through the official server-side Stripe SDK; the frontend redirects to Stripe-hosted Checkout or uses supported client SDK flows. Verify success server-side (retrieve the session or verify signed webhooks), not by trusting a browser redirect.

Suggested flow:

1. Healthy storefront can create a Stripe test Checkout Session.
2. Inject a seeded bug into the storefront's checkout request handler; requests return 500 before creating a session.
3. FORGE detects the failure, generates and verifies the fix inside CreateOS.
4. Human approves applying the patch to the demo storefront.
5. FORGE probes the repaired endpoint and creates a **new test-mode session** successfully.
6. Complete a test payment manually or through an approved automated test flow; record its verified test status.

Never send card details to FORGE's own logs. Do not use live payment keys or claim that a successful session creation equals a settled payment. For the MVP, successful test session creation + healthy endpoint is sufficient; payment completion is a stretch verification step.

## F. Vercel + worker deployment

Deploy Next.js web/API on Vercel. Run the long-lived worker separately on a suitable Node runtime (local machine for live judging or a persistent worker host). API routes enqueue jobs in Postgres; they must not block while the sandbox runs. Set secrets in deployment environment management, not the repository. Validate CORS/auth for event streams and avoid exposing internal worker routes publicly.

## G. Event flow across services

```text
[Storefront /checkout returns 500]
             ↓
[Worker health probe + Neon incident]
             ↓
[LLM diagnosis + patch proposal]
             ↓
[CreateOS sandbox: baseline fails → patch → independent tests pass]
             ↓
[Neon stores evidence; UI streams event timeline]
             ↓
[Human approves exact patch hash]
             ↓
[Demo target patched and health-probed]
             ↓
[Stripe test-mode checkout verified]
             ↓
[Incident marked recovered + audit event]

Stripe Projects provisions Neon + Vercel before this workflow.
```

## H. Failure handling

- **CreateOS auth/quota error:** mark run blocked, show actionable error; no simulated success.
- **Sandbox timeout:** cancel run, destroy sandbox, preserve partial logs.
- **LLM malformed diff:** reject and retry once with error feedback.
- **Tests still failing:** retain patch evidence; do not enable approval.
- **Approval race:** compare expected patch hash and status in one transaction.
- **Demo apply failure:** restore known-good snapshot and show rollback status.
- **Stripe test API unavailable:** mark payment verification unavailable; do not falsely claim full checkout recovery.
- **Provisioning failure:** use already-provisioned resources only after documenting the deviation; do not provision paid resources automatically.

## I. Integration acceptance checklist

- [ ] Stripe Projects initialization and provider provisioning completed successfully.
- [ ] Neon connection established from worker without leaking credentials.
- [ ] CreateOS creates, executes, and destroys a real sandbox.
- [ ] Baseline test fails before patch and independent tests pass after patch.
- [ ] Agent-generated unified diff is visible and restricted to allowlisted files.
- [ ] Approval required before modifying demo application.
- [ ] Actual running endpoint passes health probe after apply.
- [ ] Stripe test-mode session succeeds after repair (if enabled).
- [ ] Full incident event log remains visible after browser refresh.
- [ ] Public demo, source repository, and Stripe Projects share link prepared.

## Official references

- CreateOS quickstart: https://createos.sh/docs/Sandbox/SDK/Quickstart/
- CreateOS SDK reference: https://createos.sh/docs/Sandbox/SDK/Reference/Sandbox/
- CreateOS file transfer: https://createos.sh/docs/Sandbox/SDK/Tutorial/
- Stripe Projects CLI: https://projects.dev/developers/
- Stripe Projects hackathon: https://projects.dev/hackathon
- Stripe test mode: https://docs.stripe.com/testing

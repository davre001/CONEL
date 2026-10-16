# FORGE — Frontend / UI Specification

## Product direction

**Personality:** premium mission-control dashboard for autonomous software recovery. Make the agent's actions understandable, observable, and trustworthy. A developer should see the actual evidence; a judge should understand the recovery story in seconds.

**Visual system:** near-black `#090D14` background; panels `#111827`; borders `#253044`; off-white text `#F4F7FB`; muted `#94A3B8`; electric cyan `#22D3EE` for active agent execution; emerald `#34D399` for verified success; amber `#FBBF24` for approvals; coral `#FB7185` for failures. Typography: Geist or Inter for UI, JetBrains Mono for code/logs. 8px spacing scale, 12–16px radius, subtle glow only on active status. Accessible contrast and reduced-motion support.

## Information architecture

- `/` — concise marketing landing page with live demo CTA, workflow illustration, integrations.
- `/dashboard` — overview: app health, active incidents, mean time to recovery (measured), sandbox runs, incident history.
- `/incidents/[id]` — primary hackathon demo surface: diagnosis, live logs, code diff, tests, approvals, recovery proof.
- `/settings` — read-only integration connection status and demo controls; never reveal secret values.

## Desktop layout

Left 240px sidebar: FORGE mark, Overview, Incidents, Activity, Integrations, Settings. Main content with sticky topbar, environment badge (`DEMO / TEST MODE`), connection indicators, and action button. Incident detail uses 12-column grid: left 7 columns for agent timeline + terminal, right 5 for diagnosis + tests + approval. At widths below 1024px, collapse sidebar and stack panels. At mobile widths, provide readable status cards and a scrollable code diff.

## Screens

### 1. Dashboard

**Hero strip:** `SYSTEM STATUS: HEALTHY / DEGRADED / RECOVERING`, last check timestamp, monitored demo app, prominent **Inject Demo Failure** button (admin-only). Four KPI cards: Open Incidents, Verified Repairs, Median Recovery Time, Active Sandboxes. Use `—` instead of invented values.

**Main:** real-time health sparkline; incident table with id, severity, title, status, started, duration, and **Investigate** link. Right rail: latest agent events with timestamps and real source labels.

### 2. Incident detail — centerpiece

Header: `INC-1042 · Checkout API failure`, red severity pill, real elapsed timer, **Run autonomous repair** button.

**Timeline** with precise stages: Detected → Diagnosing → Patch Generated → Sandbox Running → Tests Passed → Awaiting Approval → Applying → Verifying → Recovered. Show `queued`, `running`, `passed`, `failed`, `skipped` states and actual timestamps; no stage should jump to success until a backend event confirms it.

**Live terminal:** streaming monospace lines with sandbox id (partially masked), command name, stdout/stderr, exit code, elapsed time, and copy button. Highlight errors; redact secrets and tokens before storage or display.

**Diagnosis card:** source file, error signature, root-cause explanation, confidence marked as heuristic (not probability), supporting stack-trace excerpt.

**Patch viewer:** Git-style unified diff with additions/deletions and file path, plus a changed-file count. Include a warning for any unexpected file changes and disable approval.

**Test evidence:** independent test suites; baseline result vs patched result; passed/failed counts, duration, exit code, and expandable output. Differentiate tests written before repair from any AI-generated supplemental tests.

**Approval panel:** clear `Approve & Apply to Demo` / `Reject Patch` buttons. Explain that approval changes only the demo target. Disable until tests pass and allowlisted paths are validated.

**Recovery proof:** original 500 → current 200, response contract checks, Stripe test transaction status if configured, measured time-to-recovery. Never say revenue was recovered without measured evidence.

### 3. Integrations

Cards for CreateOS, Stripe Projects, Neon, Vercel, LLM, and Stripe Payments (test). States: connected / unconfigured / degraded. Show resource names and last successful check, not raw credentials. Stripe Projects is described as **infrastructure provisioning**, not payment processing.

## Component contracts

- `IncidentStatusBadge({status})`: exhaustive mapping; unknown state renders neutral.
- `RepairTimeline({events})`: sorts by sequence number and preserves terminal states.
- `TerminalStream({incidentId})`: SSE subscribe, exponential reconnect, last-event id, polling fallback.
- `DiffViewer({patch})`: read-only diff, max line rendering for performance, path safety warning.
- `TestResults({results})`: independent suite metadata and raw evidence links.
- `ApprovalPanel({patchId, eligible, onApprove})`: requires confirmation and disables while request pending.
- `DemoFailureButton`: two-click confirmation; visible only with demo admin access.

## API interactions

- `GET /api/incidents` → paginated incident summaries.
- `GET /api/incidents/:id` → full incident, latest patch, tests, verification.
- `POST /api/incidents/:id/repair` → starts idempotent run; returns `202` and `runId`.
- `GET /api/incidents/:id/events` → SSE with monotonic `seq` and heartbeat.
- `POST /api/incidents/:id/approve` → patchId + action + idempotency key.
- `POST /api/demo/inject-failure` → guarded demo-only action.

### SSE event envelope

```json
{
  "id": "evt_123",
  "incidentId": "inc_123",
  "seq": 12,
  "type": "sandbox.command.completed",
  "at": "2026-10-14T18:00:00Z",
  "data": {"command": "pnpm test", "exitCode": 0, "durationMs": 2418}
}
```

## Interaction and animation

Use restrained 150–250ms transitions, pulsing cyan activity only during actual execution, and a single satisfying status transition when health is restored. No fake terminal typing or fabricated counters. Support skeletons, empty states, retryable errors, keyboard focus, and screen readers.

## Landing page copy

**Headline:** `Your software breaks. FORGE fixes it.`

**Subhead:** `An autonomous AI reliability agent that diagnoses failures, writes corrective code, proves its patches inside CreateOS sandboxes, and restores applications with human-approved changes.`

**CTA:** `Watch a live repair` / `Open dashboard`.

## Judge demo UX checklist

- One click to inject the seeded failure; one click to start repair.
- Evidence is visible without scrolling through many screens.
- All stages reflect backend state and remain visible after refresh.
- A failed run displays honest diagnostics and a safe retry path.
- A prepared recorded fallback is available if the LLM or sandbox provider is temporarily unavailable; clearly label recording as prerecorded.
- Never imply a real production deployment or real customer charge.

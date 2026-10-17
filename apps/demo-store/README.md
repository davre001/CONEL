# CONEL Demo Store deployment

This controlled application supplies the real checkout source defect, independent regression tests and HTTP acceptance fixture used by CONEL. Checkout accepts Stripe test credentials only. The fixture replaces Stripe locally and does not establish a payment or a model repair.

## Production image

Build from this directory, independently of the backend image:

```powershell
docker build --tag conel-demo-store:local apps/demo-store
docker run --rm --publish 127.0.0.1:3001:3001 conel-demo-store:local
```

Run these commands from the repository root. The multi-stage image installs locked dependencies without lifecycle scripts, builds Next.js standalone output, checks TypeScript and runs as the unprivileged `node` user. Only allowlisted application/build files enter the build context. Credentials are runtime configuration; do not bake an environment file into the image.

The image listens on `0.0.0.0:3001`; hosts may override `PORT`. Its container liveness probe uses `/`, allowing the server to remain reachable while the deliberately defective checkout returns failures. Configure CONEL's application monitor against `/api/health`. A host that removes traffic on `/api/health` failure can prevent the intended public failure demonstration.

Without payment configuration, healthy source returns 200 at `/api/health` and 503 for checkout POST. Supply `STRIPE_SECRET_KEY` (test mode only) and the HTTPS `DEMO_STORE_URL` privately to enable checkout. Runtime error reporting additionally uses `CONEL_API_URL`, `DEMO_STORE_PROJECT_ID` and `DEMO_STORE_MONITOR_KEY`. The production `/api/demo/break` and `/api/demo/reset` routes always return 403.

## Publish a reviewed revision

The manual [image workflow](../../.github/workflows/demo-store-image.yml) builds the source checked out at the selected Git ref. It never injects a defect during the build. Select `healthy` for the initial source: regression tests must exit 0, health GET/HEAD must return 200 and checkout POST without credentials must return 503.

For a controlled failure demonstration, commit the reviewed change from `return item.amount;` to `return item.invalidAmount;` in `lib/checkout.mjs` on the intended demo branch. Run the workflow on that exact ref with `expected_state=failing`: regression tests must exit 1 and health GET/HEAD plus checkout POST must return 500. Both states must serve `/` and reject production failure/reset controls. Never seed or deploy the failure on an unrelated application.

After those container checks, the workflow pushes `ghcr.io/<owner>/<repository>/demo-store:<commit-sha>`. Record the successful workflow run, commit and registry digest, then deploy that image to the controlled HTTPS target. Registry visibility/access must be configured for the host. Keep CONEL's selected repository, branch and `root_directory=apps/demo-store` aligned with the deployed revision. The independently authored regression and HTTP verification files must remain unchanged between the failing and repaired revisions.

Begin project registration with `repair_mode=monitor_only` until model/sandbox costs are approved. A real failure on an auto-investigate project can enqueue billable work immediately. Approving a repair publishes a PR; merge, deployment and live recovery remain separate gates.

## Verification status

Local checkout regressions, TypeScript and seeded-failure/manual-reset HTTP fixtures passed. The approved [Linux image workflow](https://github.com/davre001/CONEL/actions/runs/39074869273) then passed the production build, TypeScript, regressions and container HTTP checks against healthy committed revision `c9687537f42ddb1e0f3c3c34dbcdd193584b6ba5`. Health GET/HEAD returned 200, checkout without credentials returned 503, and production failure/reset controls returned 403.

Published image: `ghcr.io/davre001/conel/demo-store:c9687537f42ddb1e0f3c3c34dbcdd193584b6ba5`.

Registry digest: `sha256:8fc326bb877e071a7e09311d4ba4947ea278293521107089fdec1d981627961c`. Prefer the digest when deploying. A private publication receipt and sanitized job log are retained under `var/verification`. The deliberately failing revision workflow path remains unexecuted. No hosted Demo Store, public incident, Stripe payment or recovery is claimed.

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

## CreateOS deployment attempt

The dedicated Stripe Projects resource `conel-demo-store` uses the existing CreateOS Free plan. CreateOS rejected the publicly pullable GHCR reference as `invalid image`, both in digest and commit-tag forms. A flat-name alias was also published and passed the Linux build/HTTP workflow, but CreateOS rejected it too. This does not establish the cause of the registry validation failure.

The empty image-mode project was marked for deletion. Its replacement, `conel-demo-store-live` (`ac1ca584-bef6-4b83-a68f-a51b2eaa1153`), uses the Dockerfile upload runtime. The uploaded directory contains only a Dockerfile whose FROM line pins `ghcr.io/davre001/conel-demo-store@sha256:89e01ecc41ef88c1b114726abcf6db3e2f5b9dd1044d7dbf97e7337d1be2ea58`. This artifact comes from [workflow 39075399413](https://github.com/davre001/CONEL/actions/runs/39075399413), commit `9141ec77157b1e4363d48576980cb96af5923100`.

Production environment: `ae32d6e7-8c4a-4ffa-8765-fe16eb53a7ae`; one replica, 250 millicores CPU, 512 MB RAM. `PORT=3001`, `HOSTNAME=0.0.0.0` and `NODE_ENV=production` are explicit runtime variables. No Stripe payment or CONEL monitor credential was uploaded. The stable route is `https://production-conel-demo-store-live.tyzo.nodeops.app`.

The initial upload was reported deployed and promoted, but public health returned an nginx 503 and deployment-URL requests timed out. Runtime logs remained empty. The controlled retrigger also reached provider status `deployed` and was promoted: deployment `1a70a6e3-bf29-46c7-b741-479d00eb2045`. Final curl checks still returned nginx 503 on Production and a timeout on the deployment URL. Python's default client separately received Cloudflare error 1010. Runtime logs remained empty. The service remains configured at one replica; no healthy public application is claimed. Private evidence: `var/verification/demo-createos-deployment.json`. Provider runtime/routing investigation, monitoring registration and failure/recovery demonstrations remain pending.

## Public deployment verified

The stable storefront is now live at [production-conel-demo-store-live.tyzo.nodeops.app](https://production-conel-demo-store-live.tyzo.nodeops.app). Deployment `7fe0a990-ad3f-4299-80ec-d1fb07522cac` passed all six public HTTP checks: storefront and health GET/HEAD returned 200; checkout without a Stripe test key returned its expected application 503; production failure/reset controls returned 403. The storefront content and JSON health response identify CONEL Demo Store.

The successful upload wrapper now states WORKDIR, runtime environment, EXPOSE and CMD explicitly. The [checked-in wrapper](createos/Dockerfile) matches the deployed artifact. The API already reported port 3001 and Dockerfile mode before this change; the earlier attempts' exact runtime failure was not exposed in logs. The successful deployment followed this metadata change, but that does not establish which individual instruction resolved the provider behavior.

To deploy the same pinned release through the existing project:

```powershell
var/tools/createos.exe deploy --project ac1ca584-bef6-4b83-a68f-a51b2eaa1153 --dir apps/demo-store/createos
```

Promote the returned deployment ID to environment `ae32d6e7-8c4a-4ffa-8765-fe16eb53a7ae`, then repeat public health checks. Future image releases require updating the wrapper digest to the newly verified image. This is an upload deployment, so source commit metadata is tracked by the pinned image/workflow receipt rather than CreateOS's empty VCS source fields. CreateOS's OCI build warned that the image HEALTHCHECK is ignored; public HTTP checks remain required.

The private `var/verification/demo-createos-deployment.json` receipt now records the successful checks. The prior 503 observations above are historical. Monitoring registration, a controlled incident, model/sandbox repair and payment verification remain separate pending milestones.

## Monitoring connected

The live storefront is registered under the authenticated CONEL account as project `ab4e965b7c4244cba42ae0a0d928695f`, repository `davre001/CONEL`, branch `main`, root directory `apps/demo-store`, health endpoint `/api/health`, in `monitor_only` mode. Registration returned 201 and a healthy HTTP 200 observation. Passive API reads subsequently confirmed two additional scheduled healthy observations approximately 33 seconds apart. No manual health-run endpoint was invoked for that verification.

Monitor-only mode records incidents without automatically queuing model or sandbox work. Controlled source failure, actual incident capture, a cost-approved model/sandbox repair, PR review and recovery remain pending. Monitor credentials and redacted observation receipts remain private under ignored `var/verification`.

## Repair capacity gate

The operator approved the bounded controlled recovery test (up to three temporary sandbox attempts), but execution stopped before deploying the source defect. The active Free plan's documented single-sandbox allowance is occupied by retained, paused `conel-dev`; the main worker's default 2-vCPU/4-GB shape also exceeds its documented 1-vCPU/1-GB maximum. No model call, new image build or sandbox creation was attempted for this run. The storefront remains healthy.

Capacity must be increased with a reviewed price while preserving `conel-dev`. The live Stripe catalog exposed only Free, so no paid upgrade was selected. See the private `var/verification/demo-repair-capacity-preflight.json` receipt and [CreateOS limits](https://createos.sh/docs/Sandbox/Limits/).

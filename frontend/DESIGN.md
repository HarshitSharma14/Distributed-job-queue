# Relay interface implementation

The redesign retains React 19, TypeScript, Vite, React Router (`/app` basename), Tailwind 4 and React Query. Authentication remains cookie/CSRF based. There is one frontend entry point, no tenant switcher and no existing theme toggle. The role switcher selects an actual granted role; it does not change permissions.

## Route and contract inventory

| Routes (relative to `/app`) | Purpose and real API contracts |
| --- | --- |
| `login`, `password` | `/auth/login`, `/auth/me`, `/auth/logout`, `/auth/password`; temporary-password gate preserved |
| `admin` | `/admin/overview?window=1h\|6h\|24h\|7d`; exact all-time counts and separately scoped Prometheus series |
| `admin/jobs`, `admin/jobs/:id`, `admin/dead-letters` | `/admin/jobs`, `/admin/dead-letters`, `/jobs/:id`, `/jobs/:id/replay`, `/jobs/:id/result` |
| `admin/releases`, `admin/releases/:id` | Management catalog, artifact history, approve/sign, reject with reason, disable |
| `admin/workers` | `/admin/workers`, agent credential revocation |
| `admin/queues` | `/admin/queues`, `/admin/queue-controls`, pause/resume; durable and Redis counts kept separate |
| `admin/users`, `admin/audit` | Accounts, roles/status, password reset, and audit events |
| `publisher`, `producer` | Role-scoped analytics and newest eight jobs; independent partial-failure handling |
| `publisher/releases`, `publisher/releases/:id` | Create draft, example ZIP download, upload/validate handler, artifact history, next version, disable |
| `publisher/jobs`, `publisher/jobs/:id` | Publisher-scoped jobs and authorized details/results |
| `producer/jobs`, `producer/jobs/:id`, `producer/submit` | Owned jobs; active release catalog; JSON payload, priority, attempts, idempotent submit/replay |
| `producer/keys` | Create, copy/hide and revoke expiring Producer API keys |
| `worker`, `worker/agents` | Owned-agent overview, approved catalog, startup settings, enrollment and copy/hide command, credential revocation |
| `worker/assignments`, `worker/attempts` | Cursor-paginated safe execution metadata, agent/outcome filters; no unauthorized payloads or credentials |

There are 26 named route patterns plus the index and fallback redirects. Every named screen uses the shared system. There is no separate queue-detail endpoint, job-cancel action, cron/dependency UI, or log stream in this implementation. Attempt errors remain inspectable without inventing a log viewer.

## Shared system

- `styles.css` defines canvas/surface/raised backgrounds, text/border/accent tokens, semantic status colors, a compact type scale, spacing, focus states and responsive behavior. No network font dependency.
- `DashboardPrimitives` supplies headings, metrics, panels, semantic text-and-dot status indicators, accessible scrollable tables, relative timestamps with absolute tooltips, and copyable IDs.
- `Management` supplies explicit form-label associations, four button variants, section layouts, cursor/local pagination, query states and bounded, collapsible JSON (100 rendered lines per page, full-content copy).
- `InteractionProvider` owns notifications and native modal confirmations. Cancel receives initial focus; Escape cancels; the browser traps focus and restores it. Success notices dismiss automatically; errors remain until dismissed. Mutations prevent concurrent duplicate submission.
- Desktop navigation is 224px wide. Below 800px it becomes an accessible drawer with keyboard focus containment and Escape handling. Tables scroll within their regions, preserving job identity and status at the leading edge. Metrics become two columns. Detail metadata reduces to two columns at 1100px.
- Server cursor pagination is preserved at 25 items/page. Unpaginated agent/key/queue API responses use local 25-row pages to bound DOM work. Job filter state is shareable in the URL and query changes reset cursor state. No client-side sorting claims are made across partially loaded server datasets.
- Polling remains query-specific: detail/owned agents/queues 5s; overview assignments 10s; lists 15s; analytics and operational trends 30s. No real-time transport was replaced.

## Accuracy and failure behavior

Queue controls that fail to load are shown as unavailable, not implicitly unpaused. Redis failure does not hide durable counts. Worker summary counts explicitly identify the capped sample; missing durations show an em dash. Analytics and latest-job requests fail independently. Audit and release ordering is not labeled chronological because those APIs paginate by ID.

## Verification

Run `npm run typecheck`, `npm run lint` (Prettier consistency check; the repository has no ESLint configuration), `npm test`, and `npm run build` from `frontend`. Backend regression testing uses `source .venv/bin/activate && pytest -q` and the existing isolated `_test` database.

The Playwright workflow uses real API calls and actual worker execution. It covers account creation/password replacement, draft/ZIP validation/approval, enrollment, completion/download, pause/resume, failure/replay including cancellation, key and agent revocation, next-version creation, release rejection/disable, account editing/password reset, filters, role restrictions, and route screenshots at 1440px/390px. Additional fault checks delay real requests, inject only failure responses, and verify retry recovery and partial data; no mocked successful data is used in the application.

Design reference: [Inngest run inspection](https://www.inngest.com/docs/platform/monitor/traces), particularly grouping identity, attempt outcomes and input/error details. Relay retains its own visual language and only its existing domain capabilities.

### Completed local verification (2026-09-11)

- Formatting/lint, TypeScript and production build: passed.
- Frontend unit/component tests: 9 passed.
- Backend regression suite: 179 passed; no backend source changes made for this redesign.
- Real-backend Playwright workflow: passed, including 72 route/state screenshots, 320/390/768/1024/1440px checks, and recovery from injected request failures.
- Manual screenshot review included all screen families, role-specific detail actions, auth, upload instructions and confirmation dialogs. Clipboard ID/payload copying and mobile role switching also passed in Chromium.
- Local QA accounts/releases/jobs created by acceptance testing remain identifiable by their unique test names. Existing records and account passwords were preserved. Test-worker processes were stopped and their credentials revoked.
- Local Docker rollout completed: `docker compose build init` rebuilt the shared image, then `docker compose up -d --no-deps --wait api` replaced only the API container. Backend layers were cached; initialization and database migrations were not rerun. The redesigned production bundle is served at `http://127.0.0.1:8000/app/` and the API readiness check passes.
- Post-rollout Chromium smoke testing on port 8000 passed login, 20 static authenticated routes across all four roles, populated admin job/release details, mobile role switching, and logout. Production asset identity was verified; no unexpected HTTP or browser errors occurred. Desktop and mobile screenshots were reviewed. Existing QA data remains unchanged by this smoke test.

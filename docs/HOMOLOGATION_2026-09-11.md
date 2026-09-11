# Authentication Ownership Milestone

Initial HEAD: `f682ac5`.

## Real Evidence

- Cycle `bc8600f6-7e6a-4f78-b49b-37456ddeb0ef` observed the Account Picker,
  then waited for profile selection. Three manual validations did not complete.
- Read-only CDP inspection found one external-system page at `/frmMain.aspx`
  and a separate blank page. The former contained the configured profile name;
  the latter contained no identity evidence.
- The manual endpoint created a new context, not the worker's authenticated
  page. Its finally block persisted even failed validation.
- A synthetic test on the deployed Chromium proved `new_context` pages vanish
  when their owning Playwright connection stops. A storage snapshot is not a
  live-page handoff.
- Backend and worker previously mounted different profile-storage locations.

## Correction

- Persist the worker's CDP target/context IDs on AccessCycle (migration 0024).
- HTTP queues manual validation. The owning worker stops automation, inspects
  its existing page, verifies identity, saves storage, and completes the cycle.
- Keep worker-owned contexts alive, keyed by profile; reuse only the same
  profile. Release unavailable profiles and release live connections on shutdown.
- Save verified snapshots atomically with private file permissions and IndexedDB.
- Lock cycle updates; later heartbeats/events cannot revert terminal completion.
- Passive validation finds the exact profile-owned target, not a global page.
  Inconclusive passive observation preserves the durable last validation.
- Workspace status is bound to the selected cycle/profile, not global Microsoft
  status. Worker focuses the selected profile's page.
- Removed the identity-verification fallback based only on earlier picker selection.

## Validation

Tests include PostgreSQL, the actual HTTP endpoint and deployed Chromium/CDP
using synthetic routed pages. No external Action or batch was executed.
The fixture verifies current-page ownership, worker handoff, no navigation
during validation, cookie isolation, persistence, and passive validation.
Focused tests also cover wrong identity, incomplete authentication, heartbeat,
claiming, canonical access, profile deletion and canonical product integration.
Frontend typecheck and Docker/frontend builds passed.

Three incomplete authentication cycles were explicitly superseded before worker
restart to prevent unintended replay: `bc8600f6-7e6a-4f78-b49b-37456ddeb0ef`,
`883508a1-15a9-489b-8861-cf6c5b1578c0`, `7b765ca9-dcd4-4cda-a869-08b8a78201ab`.
None was linked to a LearningSession; their history remains intact.
PostgreSQL and Chromium containers were not recreated.

## Not Yet Homologated

The configured application admin credential returned HTTP 401. No password was
changed and no application session was forged. Real authenticated UI testing
requires the user's login, followed by a fresh profile authentication cycle.

Do not declare the product ready. Next inspect and fix the exact session handoff
to learning/runtime: their current code can retain the pre-cycle page/context.
Do not start a real Action until that handoff is proven against CDP. Profile CRUD
through the authenticated UI, real learning, publication, individual runs and
batches of 3/10 remain unhomologated.

## Learning Handoff Milestone

The user completed real authentication and the separate CotaSync UI login.
Managed Chromium remains exclusively for the external system.

Learning `86524f8d-2610-446a-86f0-53a411db5537` created persisted access cycle
`a4a858f6-807f-4543-bc42-57e0b8c02bf6`. The previous pending authentication
cycle was validated through the existing UI, allowing this cycle to proceed.

Two integration defects were reproduced and corrected:

- Learning retained the pre-access page. It now binds the actual verified
  CDP target/context and scopes instrumentation/events to that profile.
- GET learning returned only diagnostics, dropping access_cycle_id and session
  metadata. The UI could not show manual validation and claimed recording while
  waiting. GET now preserves the session contract; controls reflect recording.

Real UI evidence: the learning workspace showed waiting and disabled controls;
its validation button completed the cycle with verified identity; only then
PostgreSQL changed learning to recording. A separate-browser real CDP test
proves profile page isolation and the pending/resume gate. The related suite
passed 63 tests, frontend 10 tests, typecheck and Docker builds passed.

The first real recorded click on Atendimento redirected from the external
system to Microsoft rather than the query form. Recording was stopped through
the UI with one event retained for diagnosis. Nothing was published or replayed.
This new external-session transition remains under investigation; completed
teaching, publication, individual execution and batches are NOT homologated.

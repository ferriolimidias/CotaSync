# CotaSync Product Invariants

Manual authentication validation is worker-owned. HTTP requests only enqueue
validation on the AccessCycle's existing isolated session. Never create a new
browser context to validate a page reached by the user. Stop automation before
inspection, persist only verified sessions, and keep terminal cycle states
immune to later heartbeat updates. Cover this with real CDP contract tests,
not a new_context mock that returns the user's existing page.

The permanent product invariants are defined in
[`docs/PRODUCT_INVARIANTS.md`](docs/PRODUCT_INVARIANTS.md). Any change to
learning, individual execution, batch execution, or browser start behavior
must preserve them.

Violating these invariants is a product regression even when unrelated local
tests pass. Do not remove or weaken their tests to accommodate a new
implementation.

## Access Identity Rule

`ExternalSystem -> ExternalAccessProfile -> login_identifier` is the only
operational source of external identity. There is no operational global
Microsoft user, login, account-picker position, or process-wide account
fallback. Configuration and browser actions must use the same selected
`access_profile_id`; legacy fields may remain only as stored compatibility
metadata and must not become runtime authority.

## Required Review Rule

Before changing a logical start, verify the shared start policy and the
invariant tests. A residual Chromium page is never valid evidence for the
initial state of a new logical unit.

External-system latency must be handled by state-driven waiting. A wall-clock
locator/navigation probe timeout is not a logical Run failure. Runtime waits
must continue polling with cancellation and terminal browser/auth checks.

Every Run must emit a structured, secret-safe timeline sufficient to identify
whether it reached external entry, access bootstrap, main action, output, or a
terminal result. Do not remove the ordering events or log credentials, tokens,
cookies, OAuth query strings, or secret field values.

## Profile Deletion Rule

`ACCESS_PROFILE_DELETE_UNLINKS_DEPENDENCIES` is permanent: deleting an
`ExternalAccessProfile` permanently removes its identity and profile-owned
browser storage. Operational dependencies remain as records but their
profile IDs become unassigned; no Action, list, or cycle is rebound to
another profile. Execution fails closed with
`REQUIRED_ACCESS_PROFILE_NOT_ASSIGNED` until an authorized user explicitly
rebinds a profile. The same login identifier may be registered again.

## Canonical Access Flow

Authentication, learning, individual execution, and every batch client must
share one external access state machine:

`ACCESS_START -> EXTERNAL_ENTRY -> ACCOUNT_PICKER -> PROFILE_SELECTED -> LEARNED_ACCESS_BOOTSTRAP -> EXTERNAL_SYSTEM_READY`

For Microsoft account-picker flows, `ExternalAccessProfile.login_identifier`
must be selected before any learned post-selection bootstrap event. No
subsystem may start from a residual browser page, use an ordinal account-picker
position, or implement a competing identity/authentication order. Access
bootstrap is not part of the main Action graph. Any future change that
violates these rules is a product regression even if unrelated local tests
pass. See `docs/PRODUCT_INVARIANTS.md` for the permanent specification.

A new Microsoft access cycle is not valid unless the Account Picker is
actually presented and the configured `ExternalAccessProfile` is explicitly
selected during that cycle.

## Canonical Entry URL Rule

`ExternalSystem.entry_url` is the only navigation source for the beginning
of every new logical unit. Learning, individual Runs, and each new batch
client must navigate to that configured URL before access bootstrap. Action
metadata, legacy login URLs, redirects, residual browser pages, and global
URLs must never replace it. Entry reset happens once per client/logical unit,
never between steps or outputs of the same Action.

## Profile Session Isolation

`AUTH_SESSION_ISOLATED_PER_ACCESS_PROFILE` is permanent: authentication
storage belongs to `ExternalAccessProfile`, never to a global browser
identity. The same profile may reuse its session; switching profiles must
activate that profile's isolated session before access begins. Clearing a
shared context is not a substitute for per-profile isolation.

`VERIFY_EXTERNAL_IDENTITY_BEFORE_ACTION` is also permanent: being inside the
external system does not prove the correct identity. The access coordinator
must verify the requested profile before releasing an Action. These rules and
their tests must not be weakened to accommodate future implementations.

`BROWSER_PROFILE_ISOLATION_FAILS_CLOSED` is permanent: if an isolated
`BrowserIdentitySession` cannot be created, the operation must stop with
`ACCESS_PROFILE_BROWSER_ISOLATION_UNAVAILABLE`. Never substitute the global,
default, or current browser context.

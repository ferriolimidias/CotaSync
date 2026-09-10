# CotaSync Product Invariants

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

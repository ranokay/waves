# Lite session observer source extension

This optional source extension adds `GET /waves/session/v1` to the checked
user-managed lite runtime. It ships source only. It does not approve a runtime
image, native payload, transport backend or packaged application.

The exact prerequisites and patch/output SHA-256 values are in
[manifest.json](manifest.json). The prerequisites include the security
corrections identified in the [qualification record](https://github.com/ranokay/waves/issues/579#issuecomment-6117628523)
for public source `2fd7e0eaef081f93cf687428b965674937832ba4`.
Stock upstream source does not match these prerequisites.
These source hashes do not freeze dependencies resolved by the existing build.
Freeze the actual dependency commits and record output digests before native
qualification and artifact approval.

Use a separate source copy. Check it before applying:

```sh
uv run --locked --all-extras python tools/apple_lite_session/apply.py --source /path/to/checked-source
uv run --locked --all-extras python tools/apple_lite_session/apply.py --source /path/to/checked-source --apply
```

The first command writes nothing. The second applies only the exact checked
patch and verifies its output hashes. Neither command builds, starts or logs
into a runtime. Preserve the source extension's MIT notice and the source
runtime's notices when assembling a user-managed artifact.

## Session contract

The guest route accepts loopback requests only. Waves contacts it through the
inspected immutable container ID using private stdin, with no published port.
The response contains exactly:

```json
{
  "protocol": "waves-lite-session-v1",
  "authenticated": true,
  "storefront": "ro",
  "account_id": "",
  "session_revision": "0123456789abcdef0123456789abcdef:1",
  "error": ""
}
```

Authentication is `true` only after a fresh successful HTTPS request to Apple's
[user-storefront endpoint](https://developer.apple.com/documentation/applemusicapi/get-a-user%27s-storefront)
with the runtime's own current credentials and a valid single storefront
resource. Token presence, a cached storefront, and a successful refresh method
are insufficient. Authentication is `null` for unavailable, changed or rejected
evidence. HTTP 401 and 403 stay unknown because developer authorization can
also fail; the observer does not infer account logout.

The request uses the checked native CurlEasy transport, verified TLS, a fixed
HTTPS URL, no redirects or proxy, bounded headers/body and one observation at a
time. It performs no developer-token scrape, token refresh or media request.
The native policy can override the requested five-second timeout to fifteen
seconds; the guest RPC read timeout is eighteen seconds and its owned host
command has a twenty-second bound. Host cancellation discards the result and
reaps its command. Cancellation of the guest's in-flight native request and its
latency require native qualification.

The observer compares owned private credential-file identity, contents and
metadata with the running service before and after the request. Linux file
events and the service's credential generation reject interrupted or replaced
context, including changes that restore the same credential bytes. Files must
be regular, singly linked, owned by the runtime user and mode 0600; their
directory must be mode 0700. Missing, unreadable or conflicting evidence stays
unknown. The observer reads these files inside the runtime. Waves receives no
credentials or upstream response bodies.

`session_revision` contains a random service nonce and a bounded counter. It
tracks continuity and changes independently of container identity. It is not
an account identifier and contains no token-derived value. This contract keeps
`account_id` empty, so account equivalence needs user confirmation after
authentication and compatibility are established.

The fixed error vocabulary is `credentials_unavailable`,
`credential_context_changed`, `observer_busy`, `upstream_unavailable`,
`upstream_rejected`, `invalid_upstream_response`, and `observer_unavailable`.
Unknown replies have empty storefront/account fields. Entropy failure returns
an empty revision and `observer_unavailable`.

## Admission and qualification

Waves distinguishes the observed authentication result from artifact approval.
`APPROVED_LITE_SESSION_ARTIFACTS` is empty until an approval record pins the
source revision, patch digest, image digest, host platform/architecture and
source or packaged application scope. Runtime responses and configured image
digests cannot create approval. A pending artifact cannot enable account
confirmation or automatic admission.

An old runtime that returns HTTP 404 for the observer can still provide
`/status` regions. Its authentication remains unknown and its session observer
is incompatible. The legacy route cannot be promoted to an authentication
contract.

Each approved record needs installed-native transport checks, fresh
authentication, rejected/expired credentials, logout/account switches,
restoration, concurrency and cancellation evidence, plus the applicable
artifact provenance, permissions, notices and backend support review. Source
compilation and isolated tests do not establish any of those native results.
Supported native/packaged platform acceptance remains required by #584/#605.

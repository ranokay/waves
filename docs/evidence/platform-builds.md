# Platform build evidence

CI build logs are multi-hour artifacts that live on the Actions run pages;
vendoring them would bloat the repo without adding verifiability. The
durable record is the run id (linkable forever), the head SHA it ran, and
what it proved — tabulated here from `docs/platform-enablement-review.md`.
Accepted by #205; the #205 closing overclaim is corrected by that issue's
follow-up comment, and the Windows park by ADR 0009.

| Leg                                          | Run                                                                         | Head SHA                                                        | Result                                                          |
| -------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------- | --------------------------------------------------------------- |
| Linux x64                                    | [34928310777](https://github.com/ranokay/waves/actions/runs/34928310777)    | `b67bc72c0c2776fb15bae10cb055bf65a39a9d38`                      | built (1h53m) + offscreen smoke-launch passed                   |
| Linux arm64                                  | [34929398611](https://github.com/ranokay/waves/actions/runs/34929398611)    | `b67bc72c0c2776fb15bae10cb055bf65a39a9d38`                      | built (3h53m); no launch by design                              |
| Windows x64                                  | [34928310777](https://github.com/ranokay/waves/actions/runs/34928310777)    | `b67bc72c0c2776fb15bae10cb055bf65a39a9d38`                      | failed: MSVC C1002 heap exhaustion on `lazy_extractors`         |
| Windows arm64                                | [34929398611](https://github.com/ranokay/waves/actions/runs/34929398611)    | `b67bc72c0c2776fb15bae10cb055bf65a39a9d38`                      | failed: same C1002 on `lazy_extractors`                         |
| Windows x64, low-memory                      | [35019374456](https://github.com/ranokay/waves/actions/runs/35019374456)    | `d08e7a19ff2c2889707ad7150f78c64607394743`                      | failed: `cl` stack overflow (`0xC00000FD`) on `lazy_extractors` |
| Windows arm64, low-memory                    | [35019374456](https://github.com/ranokay/waves/actions/runs/35019374456)    | `d08e7a19ff2c2889707ad7150f78c64607394743`                      | failed: C1002 persists; every other module compiled             |
| Linux tests (3.12/3.13/3.14 + quality)       | [34928309207](https://github.com/ranokay/waves/actions/runs/34928309207)    | `b67bc72c0c2776fb15bae10cb055bf65a39a9d38`                      | green                                                           |
| Upstream v0.1.29 Windows legs (causal check) | [34766640853](https://github.com/iamprivacy/Waves/actions/runs/34766640853) | `709e18671a2a8decc70793514c9f57a2988fe7d4` (upstream `v0.1.29`) | both built in ~14 min (no bundled engine there)                 |

Reading note (carried over from the review): the workflow's `only` filter
creates every matrix job, so legs it excludes finish "success" with their
build steps skipped. In runs `34929398611` (11/13 skipped incl. Check out
and Build) and `35019374456` (12/14 skipped) the macOS legs prove nothing —
job conclusions, not builds. Local macOS build evidence since comes from
#243 (cold 76 m 33 s, darwin/arm64) and #245 (385 s with the
`lazy_extractors` exclusion); Windows revalidation on that recipe is still
owed.

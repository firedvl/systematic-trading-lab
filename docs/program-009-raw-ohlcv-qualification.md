# Program 009 raw OHLCV structural qualification

Program 009, `multi-hour-sector-etf-research-008`, is `TERMINAL-FAIL-CONSUMED-NO-RETRY`. Exact root
`a21491c95307ec9a2d86837c7827fccf6d32d165a069e97cf92ec050247e98c6` activated the reviewed
authority on clean synchronized main `56278b8f2dc8714f58b026b0a13d523072bb64ba`. Do not activate or
run Program 009 again.

## Terminal result

The run loaded credentials once and made nine zero-retry, redirect-disabled requests. All responses
were HTTP 200 and totaled 1,806,300 bytes. The three normal chains completed. The forced-pagination
chain retained six valid raw pages, but page six still had a continuation token. The frozen maximum
was six pages, so execution stopped without page seven, the early-close chain, or the post-split
chain.

Private evidence contains 17,281 raw rows, including 4,344 valid raw-only extended-hours rows and
12,937 canonical RTH coordinates. The qualification required 14,742 coordinates and therefore
failed. The private response-manifest SHA-256/fingerprint is
`dc8fb8bb94bd4720a5dc6bbab791045584e4718b1086ca25f2e7be05c8909cf4` /
`8c0f6de100faf7fcafb97447e9ae35a70ded710557c9e3cc5d144e36e945b37f`.
The public terminal-failure SHA-256/fingerprint is
`c4778d1600c564f34da80ff7052c39e7a4bd599685342795ccb4401a4318ea4a` /
`a8ac4102f096204f27b648519cd7b5f3796743102a3a2e49203ff47a13686f96`. The finding-free independent
review binds closeout commits `11e12d7dd39c9f8c7abef60086cd87bbd14ff603` and
`11601a8d6ff98a79020780afab40c64f6f6c9e2b`; review SHA-256/fingerprint is
`2f96ed2d40740a1f24b9ba14583478fa99cc6700735b0cecf7fbe7ec3d3cf59c` /
`6aaa8f1f0a210ae4c49449030800b5e5735ba6dade388f41fecf5304d5ef1bac`. Sixty focused tests and
1,470 full-suite tests passed with four skips.
Raw pages remain under the Git-ignored private root. No full acquisition, dataset admission, strategy
calculation, protected access, PAPER action, broker write, or live action occurred.

## Credential preflight

Program 009 retains the existing reviewed credential namespace:

```text
PROGRAM_006_ALPACA_API_KEY_ID
PROGRAM_006_ALPACA_API_SECRET_KEY
```

Check presence without loading or printing values:

```console
uv run trading-lab data acquire program-009-ohlcv credential-preflight
```

The command prints only `PASS` or one `MISSING: <name>` line per absent name. It does not construct
HTTP, activate authority, consume the one use, or write private state.

## Frozen source contract

- `GET https://data.alpaca.markets/v2/stocks/bars`
- `feed=sip`, `timeframe=5Min`, `adjustment=raw`
- `sort=asc`, `limit=10000`, `asof=2026-07-31`
- inclusive request bounds, opaque token pagination, redirects disabled, zero retries
- IWM, MDY, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, and XLY

The six immutable chains are:

| Range ID | Inclusive UTC bounds | Sessions | Coordinates | Maximum pages |
| --- | --- | ---: | ---: | ---: |
| `normal-2021-07-08` | `2021-07-08T13:30:00Z` to `2021-07-08T19:55:00Z` | 1 | 1,014 | 1 |
| `normal-2022-01-25` | `2022-01-25T14:30:00Z` to `2022-01-25T20:55:00Z` | 1 | 1,014 | 1 |
| `normal-2022-11-15` | `2022-11-15T14:30:00Z` to `2022-11-15T20:55:00Z` | 1 | 1,014 | 1 |
| `pagination-2023-05-16-to-2023-05-30` | `2023-05-16T13:30:00Z` to `2023-05-30T19:55:00Z` | 10 | 10,140 | 6 |
| `split-pre-early-close-2025-11-28` | `2025-11-28T14:30:00Z` to `2025-11-28T17:55:00Z` | 1 | 546 | 1 |
| `split-post-2025-12-15` | `2025-12-15T14:30:00Z` to `2025-12-15T20:55:00Z` | 1 | 1,014 | 1 |

The ten pagination sessions are May 16-19, May 22-26, and May 30, 2023. The complete sample has 15
sessions and 14,742 required canonical XNYS symbol/bar-open coordinates. The reviewed freshness audit
binds zero overlap with Programs 002-008 OHLCV exposure; corporate-action metadata does not count as
OHLCV exposure.

The transport budget is seven to 11 requests and responses, 8,388,608 bytes per page, 16,777,216
bytes total, 120 requests per minute, one credential load, and zero automatic retries. The pagination
chain must produce at least two pages.

## Structural boundary

A bounded response is persisted create-only under
`.trading-lab/program-009-raw-alpaca-sip-ohlcv-v1/`, fsynced, and SHA-256 receipted before parsing.
Raw validation checks JSON shape, symbols, UTC five-minute timestamps, bounds, finite coherent OHLC,
nonnegative volume and optional fields, duplicates, pagination, and transport budgets. Valid
extended-hours rows stay in raw evidence and are excluded from the authoritative XNYS RTH projection.
Only then must all 14,742 canonical coordinates be complete.

The 2025-11-28 grid is calendar-derived and has 42 five-minute bar opens per symbol. Public ledger
v3 binds 2-for-1 splits for XLB, XLE, XLK, XLU, and XLY effective 2025-12-05. Raw contemporaneous
prices remain canonical. Exact rational normalization applies only to split-spanning prior-session
same-clock share volume; no adjusted historical price surface is created.

Any missing required RTH bar fails this qualification. Later dataset policy uses whole-session
exclusion and the existing frozen loss and concentration gates. It does not interpolate, forward
fill, substitute extended hours or another feed, drop a symbol, rerank, or reuse the Program 006
quarantine as fresh evidence.

## One-use lifecycle

The lifecycle requires clean synchronized `main`, exact immutable bindings, a names-only credential
preflight, finding-free review, and the exact caller-supplied external root. Activation creates the
private root and active packet but not the claim. Execution repeats authority, Git, ledger, and
credential checks under the lock, then loads credentials once and constructs the fixed client without
HTTP. The irreversible claim is fsynced immediately before the first provider transport invocation.

A sent or ambiguous transport consumes the use permanently. The claim defaults any run without a
valid PASS receipt to `FAIL-CONSUMED-NO-RETRY`; a more detailed terminal failure record is best
available evidence, not the replay barrier. HTTP 401, 403, 429, 5xx, redirect, oversize, malformed,
pagination, structural, and persistence failures get no retry or provider fallback.

Only `provider_contact`, `credential_access`, `source_requests`, and `source_qualification` may be
true in the future active packet. `market_data_acquisition`, `real_dataset_admission`, every strategy,
research, controlled/protected, PAPER, broker-write, live, subscription, and fallback capability
stays false.

## Immutable proposal evidence

- Source commit/root: `842b9db6a973c074f57dc6f1746afc9e02b1c619` / `00839ab4108b336270809a1444bb0077e6045c8f5688c8354c0f5aec6246ab20`
- Request-plan SHA-256/fingerprint: `b7ff3f3339f0a896e08e86ca381eba3ce3fd0db21fa94474d9c3842051ffca64` / `cc8152fdf2eb4cd78cf52c302509a622a5b71b9c9c72cfabe18d7cd5510a7783`
- Authority-proposal SHA-256/fingerprint: `853cd2868704a047a62abcd543e628f5853e768c401aa1cad4a72194ee136d88` / `8594d1872a7c5d3a7db9c695483581251dfb11dea2840bf0ca2b6103aa61b429`
- Review SHA-256/fingerprint: `348f14735a258f8db17bb9af20bf54f20798b1c150638fd67fb4abc7375ebfbd` / `355690a1ec9e9fe23fea32852019e4690a39677394e668bc7b2ab1b42d111773`

The consumed authority ID is
`program-009-raw-alpaca-sip-ohlcv-structural-qualification-authority-2026-08-30-v1`.
The terminal public artifact is
`config/research/program-009-raw-alpaca-sip-ohlcv-structural-qualification-terminal-failure-v1.json`.
Program 009 permits no replay or replacement authority.

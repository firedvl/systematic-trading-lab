# Program 006 Alpaca source qualification

Program 006, `multi-hour-sector-etf-research-005`, is terminally consumed and failed. It changed
only Program 005's credential and one-use authority ordering, then ran its exact structural source
qualification once.

## Terminal outcome

Exact root `56125cd74d917c938b1076160f3a6e7c408149d4048d8b0f55f693262fec47c2`
activated on clean synchronized main `8ed3bc3f700bbf2b014527c12dc45e0e8cb26def`. The run passed
both credential-presence checks, loaded credentials once, and wrote its immutable claim immediately
before the first transport. It made 23 requests and received 23 responses totaling 2,503,402 bytes,
with zero retries.

Response 23 was the first raw page for
`pagination-split-2025-12-01-to-2025-12-12`. Parsing stopped because a bar timestamp was outside the
exact XNYS grid. The failed body was not stored. Offline checks on the 22 stored pages found all 13
symbols, the same nine fixed MDY gaps in both views, no unexpected gaps, and non-constant paired
adjustment price factors in all 11 completed pairs. No receipt, source manifest, or dataset exists.

The source-qualification result is `FAIL`. Preserve the ignored private records and pages. Do not
activate or run Program 006 again, issue replacement authority, switch sources, acquire the full
range, admit a dataset, or execute a strategy. Current code verifies the exact terminal artifact
and rejects authority derivation before credential access or state creation.

The finding-free independent review binds closeout commit
`d3e7f10d33d5926074b59913143b7190b0f1bf75`. Its SHA-256/fingerprint is
`7e79c4534ad2df67c99d70de013033f823ad650d8e35c3bdf9a8d782bba0adf9` /
`59533d3b6c151865d304ed11aaf1a9917050625ed736b7d5edb1b38995b35359`.

## Failure lineage

Program 005 failed because its required credential pair was unavailable after its immutable claim
was published. No client was built. Provider requests, HTTP responses, response bytes, Alpaca
observations, and strategy returns were all zero. The failure class is
`CONTROL-PLANE-CREDENTIAL-AVAILABILITY`, not provider data, source quality, missing data, corporate
actions, licensing, or strategy behavior.

Do not retry Program 005, create Program 005 authority v3, delete its local records, or alter its
terminal public artifacts.

## Credential presence

Program 006 expects these process-environment names:

```text
PROGRAM_006_ALPACA_API_KEY_ID
PROGRAM_006_ALPACA_API_SECRET_KEY
```

Check only their presence:

```console
uv run trading-lab data acquire program-006 credential-preflight
```

The command prints only `PASS` or one `MISSING: <VARIABLE_NAME>` line per absent variable. It may be
run repeatedly. It does not activate authority, load credential values, construct a provider client,
contact Alpaca, or write private state.

The v2 readiness review recorded a `PASS` from the intended runtime without reading credential
values into an artifact. Presence is process-local and not durable. The following historical entry
flow explains how the consumed run received its credentials; it grants no authority to rerun:

```console
read -rs PROGRAM_006_ALPACA_API_KEY_ID
read -rs PROGRAM_006_ALPACA_API_SECRET_KEY
export PROGRAM_006_ALPACA_API_KEY_ID PROGRAM_006_ALPACA_API_SECRET_KEY
uv run trading-lab data acquire program-006 credential-preflight
```

Do not paste values into a Codex message. Do not place them in `.env`, a shell profile, a command
argument, a manifest, a log, or Git. A full application restart is not needed when the same
integrated-terminal shell runs the later command. An export in another terminal does not update an
already-running Codex process or this terminal.

## Frozen scientific contract

Program 006 inherits the Program 005 qualification object exactly except for the successor's two
credential environment-variable names:

- Alpaca Basic historical equities `GET /v2/stocks/bars`.
- `feed=sip`, `timeframe=5Min`, `limit=10000`, `asof=2026-07-31`, inclusive bounds.
- Paired `raw` and `split,spin-off` chains.
- 22 sessions, 13 symbols, 13 ranges, and 26 paired logical chains.
- 28 expected and 60 maximum HTTP responses, 64 MiB, 120 requests per minute, and zero retries.
- IWM, MDY, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE, XLU, XLV, and XLY.
- The same five-session, nine-coordinate MDY quarantine and all missingness, timestamp, grid,
  corporate-action, concentration, bias, cost, delay, and protected-state controls.

Exact sessions:

```text
2020-07-27  2020-12-04  2021-02-03  2021-02-05  2021-02-10  2021-02-22
2022-11-25  2023-07-17  2024-06-10  2024-06-11  2024-06-12  2025-12-01
2025-12-02  2025-12-03  2025-12-04  2025-12-05  2025-12-08  2025-12-09
2025-12-10  2025-12-11  2025-12-12  2026-07-15
```

Exact range IDs:

```text
normal-2020-07-27
quarantine-2020-12-04
quarantine-2021-02-03
quarantine-2021-02-05
quarantine-2021-02-10
quarantine-2021-02-22
early-close-2022-11-25
normal-2023-07-17
distribution-2024-06-10
distribution-2024-06-11
distribution-2024-06-12
pagination-split-2025-12-01-to-2025-12-12
normal-2026-07-15
```

## One-use lifecycle

1. Validate clean `HEAD == main == origin/main`, the proposal, reviews, source bindings, and the
   frozen request plan.
2. Check credential presence without loading or reporting values.
3. Require the exact caller-supplied external authorization root.
4. Under the Program 006 one-use lock, revalidate Git, every binding, and credential presence.
5. Load credentials once and construct the authenticated client locally without HTTP.
6. Write the immutable claim immediately before invoking provider transport for the first request.
7. Treat that first transport attempt, any uncertain transport outcome, and every later PASS or FAIL
   as consumed. Reject every rerun and perform no automatic retry.

Missing credentials before activation write no authority. Missing credentials under the lock write
no claim. Git or binding drift writes no claim. The active authority and immutable claim use the
separate Git-ignored `.trading-lab/program-006-free-alpaca/` root.

## Current authorization gate

Current status is `TERMINAL-FAIL-CONSUMED-NO-RETRY`. Every effective authority flag is false. The
credential preflight remains only a names-only diagnostic; neither `activate` nor `run` is allowed.
Controlled evaluation, protected access, PAPER, broker writes, and live execution remain untouched
and prohibited.

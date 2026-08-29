# Program 006 Alpaca source qualification

Program 006, `multi-hour-sector-etf-research-005`, is the prospective control-plane successor to
terminal Program 005. Program 005 remains consumed and failed. Program 006 changes only credential
and one-use authority ordering; Alpaca source suitability remains unobserved.

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

The v2 readiness review records a `PASS` from the intended runtime without reading credential
values into an artifact. Presence is process-local and not durable. In the Codex integrated
terminal, use one shell session for entry, preflight, and any later separately authorized
qualification command:

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

Current status is `READY FOR NEW EXACT ONE-USE QUALIFICATION AUTHORIZATION`. Proposal v2 and its
finding-free review remain inactive. The external root binds the exact final synchronized main
commit and must be supplied separately by the user. Until activation, all authority flags are
false. No provider request, qualification, acquisition, dataset admission, strategy execution,
controlled evaluation, protected access, PAPER action, broker write, or live action is allowed.

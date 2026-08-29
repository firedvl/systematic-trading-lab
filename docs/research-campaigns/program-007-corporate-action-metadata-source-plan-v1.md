# Program 007 corporate-action metadata source plan v1

## Status

Program 007, `multi-hour-sector-etf-research-006`, remains
`PROPOSED-NOT-AUTHORIZED`. This plan grants no credential, provider-request, source-qualification,
OHLCV, dataset, strategy, controlled, protected, PAPER, broker, or live authority.

Ledger v2 remains authoritative and incomplete. It resolves ten symbols and leaves IWM, MDY, and
SPY `COVERAGE-UNRESOLVED`. This plan does not create ledger v3 or a real metadata observation.

## Scientific role

The public evidence remains valid corroboration, but its stated scope cannot prove that no forward
split exists for IWM, MDY, or SPY. The proposed replacement is one frozen structured-source
contract for all thirteen ETFs. It does not weaken the action requirement: an empty result counts
only after both identity chains return HTTP 200, exhaust every page, pass the current schema,
reconcile identities, and recover all five known positive controls.

`COMPLETE-NO-APPLICABLE-UNIT-CHANGING-ACTIONS` would mean that this exact provider, endpoint,
complete identity history, query, date, pagination, and data-quality contract returned no applicable
event for the security. It would not mean that the fund has never had a corporate action. The
current synthetic candidate cannot use that conclusion because predecessor-identity closure is not
yet proved and Alpaca supplies no bounded finality guarantee for late records.

## Current Alpaca contract

The current REST contract was retrieved on 2026-08-29 from Alpaca's
[Corporate Actions endpoint](https://docs.alpaca.markets/us/reference/corporateactions-1) and its
[OpenAPI-backed Markdown](https://docs.alpaca.markets/us/reference/corporateactions-1.md). The June
2026 [region changelog](https://docs.alpaca.markets/us/changelog/2026-06-03-market-data-9dddd18)
and May 2026 [event-type changelog](https://docs.alpaca.markets/us/v1.1/changelog/2026-05-22-corporate-actions-5c87d2b)
provide change history.

- Method and endpoint: `GET https://data.alpaca.markets/v1/corporate-actions`.
- Authentication: `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` request headers.
- Fixed parameters: `region=us`, `start=1990-01-01`, `end=2026-08-29`, `limit=1000`,
  `data_quality=complete`, and `sort=asc`.
- `types` is omitted. The adapter parses all current arrays and rejects an unknown array.
- Redirects are disabled. Page tokens are opaque and must be exhausted without repetition.

No retrieved official Alpaca document guarantees Basic or free-plan access or full plan-specific
history. A future HTTP 403 therefore records terminal `METADATA-ACCESS-FAIL`, consumes the sent
one-use authority, and stops. It cannot trigger a purchase, retry, or fallback provider.

Alpaca documents `start` and `end` as inclusive and says results sort by `process_date`; it does not
state which date field those filters use. It also warns that records can be delayed without giving a
maximum completion lag. The broad 1990-01-01 through 2026-08-29 interval predates every fund in the
frozen universe and encloses the 2020-06-26 through 2026-07-31 target dates, but it cannot prove that
an action effective near the end was not processed later. This is a terminal pre-authority blocker.
Before a one-use grant, Program 007 must bind documented filter semantics and a maximum lag, wait for
that lag after 2026-07-31, and freeze a new exact query end. If no bounded finality contract exists,
authority remains blocked.

## Identity queries

The exact CUSIP map is:

| Symbol | CUSIP | Symbol | CUSIP |
| --- | --- | --- | --- |
| IWM | `464287655` | XLF | `81369Y605` |
| MDY | `78467Y107` | XLI | `81369Y704` |
| SPY | `78462F103` | XLK | `81369Y803` |
| XLB | `81369Y100` | XLP | `81369Y308` |
| XLE | `81369Y506` | XLRE | `81369Y860` |
| XLU | `81369Y886` | XLV | `81369Y209` |
| XLY | `81369Y407` |  |  |

Qualification runs one sorted current-symbol chain and one sorted current-CUSIP chain. Relevant event inventories
must match by provider event ID, and matching IDs must normalize to the same content. Any mismatch,
duplicate, or known symbol/CUSIP conflict fails. Matching events count once.

The current REST documentation does not prove that a query by a current identity returns events
indexed only under a predecessor ticker or CUSIP. Two agreeing current-identity chains could therefore
agree on an omission. Identity-history closure is an explicit pre-authority blocker. Before a real
one-use authority can activate, a reviewed artifact must bind every predecessor symbol and CUSIP for
all thirteen funds, or bind current provider documentation that proves predecessor-event closure.
Verified predecessor identities then join both query sets and the reconciliation tests. Until that
gate passes, a synthetic empty inventory remains
`PROVISIONAL-NO-APPLICABLE-ACTIONS-COVERAGE-CLOSURE-UNPROVEN`. The same provisional label remains
until the source-finality gate passes.

## Event policy

The REST OpenAPI currently defines sixteen types:

`reverse_split`, `forward_split`, `unit_split`, `cash_dividend`, `stock_dividend`, `spin_off`,
`cash_merger`, `stock_merger`, `stock_and_cash_merger`, `redemption`, `name_change`,
`worthless_removal`, `rights_distribution`, `partial_call`, `reorganization`, and
`capital_gains_distribution`.

The adapter preserves provider event ID, all symbol/CUSIP/ISIN identities, event type, subtype,
`process_date`, available ex/effective/record/payable dates, provider rates, source identity, and an
exact share factor only when the REST contract supports one.

Program 007 uses `ex_date` for splits and distributions and `effective_date` for unit splits,
mergers, and reorganizations. Redemption, name change, worthless removal, and partial call have no
unambiguous effective field in the current REST contract. This is versioned classification policy,
not a provider guarantee of universal economic timing. `process_date` is never substituted for an
ambiguous effective date.

Only a stable-identity forward or reverse split is deterministically transformable. Its factor is
the exact decimal-derived `Fraction(new_rate) / Fraction(old_rate)`. Cash dividends and capital-gain
distributions are non-unit metadata. Every other unit or identity-relevant type is nontransformable
unless later authoritative semantics prove an exact mapping. An applicable nontransformable action
or ambiguous date blocks ledger admission.

Raw contemporaneous prices remain unchanged. Exact split factors apply only to prior-session,
same-clock share counts used in relative-volume comparisons. The adapter does not create adjusted
historical prices.

## Controls

The structured feed must reproduce one 2-for-1 forward split effective `2025-12-05` for each of XLB,
XLE, XLK, XLU, and XLY. A missing, different, duplicated, or unreconciled control fails. Public
evidence cannot repair the provider result.

XLF, XLI, XLP, XLRE, and XLV are negative reconciliation controls. Non-unit actions are allowed. A
new unit or identity-changing action blocks completion for prospective investigation; ledger v2
cannot be used to discard it. The same structured contract applies to IWM, MDY, and SPY.

## One-use envelope

The proposal has two logical chains and permits two to eight HTTP GET requests and responses. Each
chain may use at most four pages. Each response is limited to 1 MiB, all responses to 8 MiB, credential
loading to once, and automatic retries to zero.

The future private root is `.trading-lab/program-007-corporate-action-metadata-v1`. Before any
transport, the implementation must persist the exact request intent. For each bounded response it
must persist bounded raw bytes and a SHA-256 receipt before size, status, or schema parsing. An
over-limit response retains at most the 1 MiB prefix and a receipt that records observed bytes,
retained bytes, the response hash when available, and truncation before it fails. Evidence is create-only
and private. Public Git may receive reviewed canonical metadata and non-secret provenance only when
licensing and repository policy allow.

Identity-history closure, bounded source finality, and a reviewed real transport/store are
preconditions. The lifecycle is:
credential presence, exact request plan and private root, separate user grant,
lock and revalidation, one credential load and GET-only client construction, one-use claim immediately
before transport, bounded zero-retry execution, then terminal evidence preservation. Missing
credentials before transport do not consume the use. A sent or ambiguous request does.

## Current implementation boundary

`program_007_corporate_actions.py` implements the frozen request intents, all sixteen schema maps,
normalization, reconciliation, controls, and in-memory successor candidate generation against finite
synthetic responses. It has no credential reader, HTTP client, arbitrary response callback,
caller-selected storage root, broker path, or real execution entry point. Its temporary evidence file
exists only to test raw-first ordering.

A real authority implementation is deliberately absent. It must add the exact ignored persistent
root behind a separately reviewed active one-use authority. It must not turn the synthetic entry
point into a generic transport hook.

## Ledger disposition and next gate

Ledger v2 and all public State Street, SEC, NYSE, iShares, and other cited evidence remain unchanged.
A successful future metadata qualification may produce ledger v3 only after reconciling all thirteen
symbols, passing the positive and negative controls, and passing independent review. It still may not
start Program 007 OHLCV qualification automatically.

No grant is ready now. After identity-history closure, documented filter and bounded-lag semantics,
elapsed finality, and a newly frozen query end, the exact next grant would be **ONE-USE PROGRAM 007
CORPORATE-ACTION METADATA QUALIFICATION ONLY**, bound to the final reviewed real transport, persistent-store
implementation, and this exact plan. It would
not authorize OHLCV, dataset admission, strategies, returns, controlled or protected access, PAPER,
broker writes, live execution, paid access, or another provider. This task does not execute that grant.

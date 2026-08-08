# Intraday research campaign v1 preregistration

Status: preregistered; real-data execution blocked because this isolated worktree has no independently available Alpaca historical credentials.

Campaign ID: `intraday-research-v1`

Plan: `config/research/intraday-campaign-v1.json`

Plan fingerprint: `ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a`

Reviewed M5B base: `b1774f547da2976348430b820faf2ebdacdf46af`

The plan tests the M5B data, replay, registry, report, stress, and research-gate path. It does not search for a profitable strategy. A passing assessment would remain research evidence only.

## Frozen data design

The provider request is read-only Alpaca IEX, adjusted for all provider-supported actions. Every dataset contains only SPY and QQQ `5m` bars from the XNYS regular session. Timestamps label bar opens in UTC. Each period must be sealed and validated as its own immutable dataset before any candidate can run.

| Role | New York sessions | Exact inclusive UTC bar-open range | Sessions | Expected bars per symbol | Early closes |
| --- | --- | --- | ---: | ---: | ---: |
| Training | 2025-07-01 through 2025-12-31 | 2025-07-01T13:30:00Z through 2025-12-31T20:55:00Z | 128 | 9,876 | 3 |
| Validation A | 2026-01-02 through 2026-02-27 | 2026-01-02T14:30:00Z through 2026-02-27T20:55:00Z | 39 | 3,042 | 0 |
| Validation B | 2026-03-02 through 2026-04-30 | 2026-03-02T14:30:00Z through 2026-04-30T19:55:00Z | 43 | 3,354 | 0 |
| Validation C | 2026-05-01 through 2026-06-30 | 2026-05-01T13:30:00Z through 2026-06-30T19:55:00Z | 41 | 3,198 | 0 |

These windows cover about six training months followed by three contiguous two-month validation windows. The dates were chosen before strategy results. Data after 2026-06-30 is outside this campaign. This exclusion does not create or designate a protected holdout.

Any missing interval, duplicate, invalid OHLCV record, out-of-session bar, unexpected symbol, range mismatch, or failed dataset validation remains evidence and stops the affected candidate. The campaign does not repair or fabricate bars.

## Frozen strategies

The strategy set and parameters are the M5B engineering baselines:

1. `intraday-cash`, with no parameters;
2. `intraday-previous-bar-momentum`, with `lookback = 1`;
3. `intraday-moving-average-trend`, with `window = 12`.

Every strategy is long-only, unlevered, limited to one-half weight per symbol, and flat at each normal or early XNYS close under `XNYS-regular-session-flat-v1`. The campaign has no opening-range breakout, parameter neighbors, parameter search, shorting, leverage, options, or extended-hours data.

## Frozen costs and delays

| Role | Model | Slippage | Commission | Whole-bar delay |
| --- | --- | ---: | ---: | ---: |
| Base | `conservative-bps-v1` | 5 bps | 1 bp | 1 |
| Increased cost | `intraday-increased-cost-bps-v1` | 10 bps | 2 bps | 1 |
| Harsher cost | `intraday-harsher-cost-bps-v1` | 20 bps | 5 bps | 1 |
| `plus-1-bar` | `conservative-bps-v1` | 5 bps | 1 bp | 2 |
| `plus-2-bars` | `conservative-bps-v1` | 5 bps | 1 bp | 3 |

The values cannot change in campaign v1. The stress roles must keep the exact order and parent lineage required by `intraday-qualification-policy-v1`, fingerprint `42481069d9d0295d40ff1ccc6c956632d852f58522040d01024d7798172fe127`.

## Candidate reservations

Each strategy-period pair reserves five consecutive candidates in this order: base, increased cost, harsher cost, `plus-1-bar`, and `plus-2-bars`. Every stress candidate names that pair's base candidate as its parent. The fixed search budget is 60.

| Strategy | Training | Validation A | Validation B | Validation C |
| --- | ---: | ---: | ---: | ---: |
| Cash | 1–5 | 6–10 | 11–15 | 16–20 |
| Previous-bar momentum | 21–25 | 26–30 | 31–35 | 36–40 |
| 12-bar moving-average trend | 41–45 | 46–50 | 51–55 | 56–60 |

The official M5B assessor will run once for each of the 12 base candidates with only its four reserved children. Reports remain separate; the campaign will not produce a composite ranking score. Pending, failed, rejected, and completed candidates all count against the fixed budget and remain visible.

## Change control and stop rules

The strict plan loader rejects changed strategies, parameters, XNYS ranges, role ordering, costs, delays, policy identity, candidate ordinals, parameter neighbors, or authority flags. Inspect it without creating runtime state:

```console
uv run trading-lab experiment inspect-intraday-plan --spec config/research/intraday-campaign-v1.json
```

Seal all 60 reservations atomically in the official registry before data binding or execution:

```console
uv run trading-lab experiment plan-intraday --spec config/research/intraday-campaign-v1.json
```

The sealed campaign rejects arbitrary `run-intraday` candidates. After one planned period dataset seals and validates, run a reservation with only its stored candidate ID, campaign ID, and exact dataset ID:

```console
uv run trading-lab experiment run-planned-intraday CANDIDATE_ID \
  --campaign intraday-research-v1 \
  --dataset DATASET_ID
```

The command verifies provider, timeframe, adjustment, XNYS and timestamp policies, symbols, requested range, actual range, dataset identity, and universe provenance. It derives the strategy, split, costs, delay, parent, code revision, reason, and ordinal from the stored plan. A mismatch fails before dataset binding or data loading and leaves the reserved candidate as failed evidence.

After the first observed strategy result, any change requires a new campaign version. A software defect invalidates the affected campaign version; it must not be silently rerun under the same identity.

The 60 reservations are sealed in this worktree's isolated registry. Real execution may begin only after this isolated process receives independent historical credentials and all four datasets seal and validate. The active daily M5 runtime, its state, credentials, authorization, and activation remain outside scope.

No protected intraday holdout exists. This plan cannot create, authorize, inspect, or reveal one. It also grants no paper, broker-write, or live authority.

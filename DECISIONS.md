# Architecture decisions

## 2026-08-23 — Derive Opening Breakout launch readiness from full validation

- Decision: report Intraday Event Opening Breakout 001 as launchable only when the complete launch-control loader accepts the artifact, implementation hashes, quality evidence, equivalence evidence, independent review, clean source identity, and source lineage.
- Context: the first exact-main review found that non-null binding constants alone could make the read-only plan surface report ready even when the artifact was missing, changed, or stale. The run path still failed closed, but the operator-facing prelaunch signal was wrong.
- Consequences: missing, hash-mismatched, or stale launch evidence leaves both `launchable` and `launch_control_bound` false. Exact implementation main `017a7cbd91a151fbdc0ddf80f5f580f0c3f9eb34` passed the corrected finding-free review; launch-control SHA-256/fingerprint `dc42631f93e0e9dd91ad2b9c22f743a1a257a890bb709cf6256b62e8877cda9e` / `871b06339bf1d26900dec25b818ba37f51a30f4091a9ad42e2d8f48b2e79dc62` bind it without granting qualification, controlled, PAPER, broker-write, or live authority.
- Revisit when: a versioned common launch-state API replaces campaign-specific plan summaries while preserving the same fail-closed evidence contract.

## 2026-08-23 — Give Event Opening Breakout one exact three-field run identity

- Decision: identify each Intraday Event Opening Breakout 001 run only by candidate, period, and scenario. Use one campaign-owned runner and event ledger while reusing the existing five-minute engine, attempt store, spawned executor, cost model, and explicit Event Drift base payload.
- Context: discovery, walk-forward, stress, and neighbor screens can request the same evidence. Including a stage or base candidate in identity would duplicate work and break the frozen 46-specification limit. Reusing a prior campaign runner would also carry campaign-specific arms, reports, gates, and source bindings.
- Consequences: exact matching evidence is reserved once and reused across stages. The runner recomputes event and release-class accounting from its ledger, requires equal signals across cost and delay scenarios, rejects broker state in coordinator and workers, and requires exact merged-main review before launch control binds. It adds no qualification, controlled, holdout, PAPER, broker-write, live, or promotion authority.
- Revisit when: never within this campaign after its first reservation. A different identity, screen, strategy, or protected-data rule requires a new prospective campaign.

## 2026-08-23 — Chain campaign CLI wrappers without changing historical source

- Decision: route the `trading-lab` console entry point through the current campaign wrapper. The Event Opening Breakout wrapper handles only its own research command and delegates every other argument to the Event Repricing wrapper, which still handles only its command and delegates the rest unchanged to `public_cli.main`.
- Context: Event Drift launch control binds the exact `public_cli.py` bytes. Adding the new command there would invalidate its immutable source check even though the closed campaign must remain reproducible.
- Consequences: `public_cli.py` keeps SHA-256 `6b96a9605291335724415c9e5a812d42e51b53571cd9b1e85679629842e47fca`. Existing commands and the terminal Repricing command retain their parsers and dispatch. Event Opening Breakout launch control must bind the complete wrapper chain with its other implementation files before the first reservation.
- Revisit when: a separately reviewed versioned command registry can preserve past campaign identities without binding one shared mutable CLI file.

## 2026-08-22 — Preserve the aborted Exposed 004 launch and rekey recovery as Exposed 005

- Decision: close `intraday-exposed-004` as immutable pre-attempt infrastructure evidence and use `intraday-exposed-005` for the corrected clean campaign. Canonicalize each 005 run specification before reservation and process dispatch. Make the generic spawned-process executor preflight every task with the spawn pickler before it starts workers.
- Context: the reviewed 004 launch reserved 120 discovery specifications, but each retained nested `MappingProxyType` values from the frozen configuration and authority mappings. `multiprocessing.Queue` serializes asynchronously, so all four feeder threads raised `TypeError: cannot pickle 'mappingproxy' object` while the coordinator waited for work no worker could receive. The coordinator stopped with no attempt, claim, report, or strategy execution. Its frozen plan requires a proven implementation defect to stop and be documented rather than repaired in place.
- Consequences: the 004 root and database remain unchanged with 120 pending rows, zero attempts, and database SHA-256 `9961bc06bc272ab6e7f772a192fe99876a8032ff0bfbf9f830a42715a14389a1`. The 004 run command is disabled; plan and status stay read-only. Exposed 005 receives a new program ID, candidate IDs, runtime root, database, reservations, attempts, reports, source commit, plan, prospective review, and launch review. It imports no 003 or 004 runtime row and changes no strategy, data, cost, chronology, screen, stage, qualification, or authority rule. Canonicalization preserves canonical JSON and fingerprints; synchronous preflight turns any future unsupported process task into a failure before worker start or claim. Launch control binds implementation main `1d6744432ed2635ce6ae19268b64b1c89fc0017d`, all seven gates, fresh exact four-fixture equivalence, both preserved dispositions, and a finding-free review at SHA-256 `6b431eb34de1cce4a0126fa10d42685bc55abf28587a15ade466912c0cbe3b94` and fingerprint `f05a789b5e4bcc71d21485d8c95237ac29fc864013521cd7a4b1e8383fbded1d`. Launch still requires clean exact merged main.
- Revisit when: a remote executor replaces local spawn or the process transport supports an independently reviewed immutable task envelope other than canonical JSON values.

## 2026-08-22 — New research campaigns may use bounded local worker processes

- Decision: add one spawn-based local process executor for stages whose immutable runs are independent. One coordinator owns stage order and screening. It dispatches at most four runs by default, waits for the whole stage, and consumes results in frozen specification order. Each persistent worker initializes its own immutable data cache, handles one run at a time, and uses its own `ResearchAttemptStore` connection, claim, heartbeat, failure, and publication calls. A dead process does not cause the coordinator to reassign its claimed run; only the existing lease-expiry path can make that exact run retryable.
- Context: restart-safe attempts already serialized claims and publications correctly, but Intraday Exposed 003 evaluated every independent row in one process. Threads do not improve the CPU-bound replay. Retrofitting the running Exposed 003 runtime would change its execution boundary.
- Consequences: future campaigns can opt into bounded process execution without changing strategy, data, cost, screening, qualification, or protected-data rules. The executor drains unaffected work after one worker fails, retires a worker after any task exception, and returns results in input order, not completion order. SQLite keeps rollback journaling and its 30-second busy timeout because four-process contention tests pass and WAL would make the existing single-file database hash incomplete. Output sealing now occurs before the short publication or deterministic-failure write transaction. Exposed 003 execution remains unchanged; its added equivalence action is read-only and compares source-database and dataset hashes before and after replay. Exposed 005 launch requires a fixed-hash control artifact that binds exact source files, all quality gates, equivalence output, preserved 003/004 dispositions, and an independent review.
- Revisit when: measured six-worker execution improves fixed-workload throughput without SQLite lock failures, missed heartbeats, swap pressure, or unsafe aggregate memory use; a remote executor or a database evidence format that includes WAL state needs a separate design.

## 2026-08-21 — Re-execute the exact Exposed 002 design as Intraday Exposed 003

- Decision: freeze a new `intraday-exposed-003` plan that loads the exact reviewed Exposed 002 plan, amendment, data binding, cost model, mechanics, chronology, strategy grid, gates, and cohort rules. Rekey only campaign identities and use `research-attempts-v1` with at most three infrastructure attempts. Do not import Exposed 002 runtime rows or use its partial results to change the design.
- Context: Exposed 002 ended after its runner disappeared with 4 completed, 1 failed, and 115 pending discovery rows. Its no-retry lifecycle made that operational interruption terminal without producing a qualification result. The partial rows are exposed evidence, so any adaptive change would contaminate a clean re-execution.
- Consequences: Exposed 003 has new candidate, reservation, run, attempt, database, and report identities while retaining all 60 parents and 120 Normal/zero discovery rows. Its runner preserves the Exposed 002 evaluation-start wrapper and passes each plan-bound `ie002-` source candidate to the unchanged strategy while keeping `ie003-` evidence identity. It reuses the four physically pre-June datasets and calibrated cost model without reacquisition or recalibration. Committed Intraday V2 exposure metadata makes June ineligible; no June read, substitute range, controlled plan, or controlled-qualification claim is allowed. A proven mechanics defect stops the campaign before execution instead of being repaired in place.
- Revisit when: never after the first Exposed 003 strategy result. A different design, controlled range, or mechanics change requires another prospective campaign.

## 2026-08-21 — New deterministic campaigns may retry vanished infrastructure attempts

- Decision: add one generic `research-attempts-v1` registry for prospectively versioned deterministic campaigns. Keep each immutable run specification separate from up to three append-only execution attempts. Renew private leases with heartbeats. Only an expired no-result lease may return the same run to pending. Journal one canonical report before create-only file publication. Treat candidate exceptions, data-integrity failures, canonical publication conflicts, and the third expired attempt as terminal.
- Context: Intraday Exposed 002 completed four rows, then its process disappeared while the fifth row was claimed. Its frozen lifecycle stored no attempt ID, time, PID, host, heartbeat, output, exit status, or resource telemetry. Its required recovery converted that stale claim to terminal failure and ended the 120-row campaign without a qualification outcome. Host inspection found no reliable cause evidence.
- Consequences: new opted-in campaigns retain stdout, stderr, exit status when known, start and end times, source SHA, immutable run fingerprint, hostname, PID, memory, disk, load, and duration evidence around each attempt. Attempt identities and events reject update and deletion. Completed canonical bytes cannot change or create retry authority. Existing campaign runners, databases, reports, and stale-run rules remain unchanged. The registry adds no strategy, data, qualification, holdout, paper, broker, or live authority.
- Revisit when: measured concurrent-worker volume exceeds SQLite, a remote executor can attest process outcomes, or a campaign needs a reviewed infrastructure-failure class beyond an expired no-result lease.

## 2026-08-20 — Bind Exposed 002 datasets to their exact local catalogs

- Decision: runner v2 dispatches the three frozen pre-May dataset IDs only through `data_home/intraday-exposed` and the frozen May dataset ID only through `data_home`. It does not scan, relocate, rebuild, or fall back between catalogs. The chosen service still performs the existing manifest, byte, full-integrity, range, and pre-June checks before runtime state exists.
- Context: PR #152 merged runner v1 at `794045775d323f1ba2481b44a454be4386bc7edd`. Its first CLI invocation used one main-root `DatasetService` for all four bindings and stopped with `dataset not found` because the three historical datasets remain in the isolated catalog. The failure happened before full validation, bar loading, runtime-directory creation, a database or run row, or a strategy result.
- Consequences: the pre-result failure is not retried or deleted because it created no mutable campaign state. Runner v2 has a new source identity and must pass independent review, CI, merge, and the clean exact-main gate before the first strategy result. Strategy mechanics, costs, periods, gates, dataset identities, June prohibition, and all false authorities remain unchanged.
- Revisit when: never within Intraday Exposed 002 after its first strategy result. Moving a frozen dataset requires a separate prospective decision and review.

## 2026-08-20 — Freeze Exposed 002 mechanics and accounting before results

- Decision: use one isolated Exposed 002 engine, registry, and CLI. Strategies emit only binary `0` or `0.5` desired weights after completed five-minute bars. Changed states queue FIFO for the frozen scenario delay, never supersede, never resize, and permit one entry per symbol and session. Existing pre-cutoff entries and exits retain their eligible fills; the controller projects the remaining queue and adds a final-open flatten when its final state is invested. Derive every family rule and metric by the exact formulas in `docs/research-campaigns/intraday-exposed-002-program.md`.
- Context: the prospective plan froze families, axes, periods, costs, screens, and terminal actions, but the runner still needed exact causal event order, cost-filter estimates, aggregation rules, and metric definitions before its first result.
- Consequences: a run must start from a clean commit where `HEAD`, local `main`, and `origin/main` match. The source gate runs before plan or data access. The runner uses only the four physically pre-June datasets, writes only `intraday-exposed-002.sqlite3` and create-only campaign artifacts, makes interrupted work terminal, and creates no controlled plan. Independent read-only review found no remaining P0, P1, or P2 issue after the focused regression fixes. No strategy, June, V3, protected result, PAPER/broker/live state, or `strategic-allocation-21` state was accessed while fixing the mechanics.
- Revisit when: never within Intraday Exposed 002 after its first strategy result. A different event rule, formula, range, or authority requires a new prospective program.

## 2026-08-20 — Preserve pre-June transport records outside the normalized grid

- Decision: keep every mapped raw record returned by the exact Exposed 002 May GET, including records outside the XNYS normalization grid through May 29 at 20:00. Require every raw timestamp to remain strictly before June, while normalized Parquet and manifest requested and actual ranges must end at May 29 at 19:55. Bind both surfaces by exact hashes and counts.
- Context: plan v1 required raw records to end at the normalized final bar. Alpaca returned 383 extra May transport records, while the existing reviewed adapter correctly retained them before publishing the exact 3,120-bar regular-session dataset.
- Consequences: plan v1 cannot bind the artifact and remains historical evidence. A narrow v2 amendment changes only the transport cutoff before data binding or strategy results. Its independent final-byte review passed with no findings at SHA-256 `a739b1e5bb82d0c03640e5d9fd13a4d1edc3b77c1865ed7a065520f9d3c11aa3`, fingerprint `38a359ce9eb04243ba4092e7eb70c7239a46ac738de3ccbd09b6ddde31325976`. Raw deletion or filtering, June access, a substitute dataset, and outcome-based selection remain forbidden.
- Revisit when: never within Intraday Exposed 002. A later program may use a provider contract that separates complete transport evidence from normalized range identity before acquisition.

## 2026-08-20 — Require a physically bounded May artifact

- Decision: do not use the existing May–June Parquet for Exposed 002. After the prospective plan merges, acquire QQQ/SPY IEX five-minute bars for May 1–29 through the GET-only Alpaca historical adapter and publish a separate artifact with no June market-data timestamp. Require normalized Parquet and manifest ranges to end at May 29 at 19:55, and freeze and independently review the exact binding before strategy execution.
- Context: datasets use Parquet without row-group statistics. A filtered read can scan June rows from the existing combined artifact before returning the May predicate.
- Consequences: the preregistration binds only the three existing datasets through April. The exact May binding passed full validation and independent review at SHA-256 `3d6a5dde3b05369ceeb1e3be5b1f47e73a541c74eed184e1850945ee56890769`, fingerprint `b6849987e7673c4073272ec891e7f7118b91eba6926aa4c16f262162f529ea9d`; review SHA-256 is `16e1ae6bc4f718f5086eec15dfcdab61fa1a2ca57ce85dab73de8fbb045e3701`, fingerprint `bae2ed10678d5a18c916773b1dcfe0b11d3b26f1f7ec2d2ec9e88dd88965d444`. Binding merge, runner merge, and exact runtime-main checks remain separate gates. Full validation is allowed only for artifacts physically bounded before June.
- Revisit when: never within Intraday Exposed 002. Storage-level partitions or row-group evidence may support a different boundary in a later program.

## 2026-08-20 — Treat June as exposed and stop before controlled evaluation

- Decision: preserve `intraday-exposed-002-june-reservation-v1.json` as historical evidence but supersede its clean-range conclusion. The committed exposure inventory already records real-market Intraday V2 results through June 30, 2026. Intraday Exposed 002 must not read June, create a June controlled plan, or choose another range.
- Context: the first audit checked Exposed 001 and active registry metadata but omitted the committed V2 exposure entry. A second metadata-only review found the conflict without opening V2 results or market data.
- Consequences: research may proceed only through May. An empty cohort closes as failed exposed evidence. A nonempty cohort freezes with blocker evidence and stops before controlled evaluation; it remains exposed-serious and cannot be called controlled-qualified.
- Revisit when: never within Intraday Exposed 002. A future controlled range requires a separate prospective program and policy review before its first bar.

## 2026-08-20 — Freeze a 60-parent sparse Intraday Exposed 002 search

- Decision: test ten causal families with two small axes and six points each. Use fixed half-weights, no resizing, at most one entry per symbol per session, paired Normal/zero runs, four chronological folds through May, visible cost-efficiency gates, Stress A/B, isolated delay-2/delay-3, immediate neighbors, and a zero-to-five cohort with at most one candidate per family.
- Context: the prior campaign showed that raw signal without enough edge per trade could not pay its frozen costs. The calibrated model supports a prospective search focused on turnover, holding time, gross trade edge, and cost-to-gross-profit rather than frequent state changes.
- Consequences: all 60 parents complete discovery before uniform screening. Weak points stop there. No hidden score, post-result threshold change, old candidate replay, one-minute acquisition, June read, controlled qualification, paper, broker-write, or live authority exists.
- Revisit when: do not change the plan after a strategy result. Any later design requires a new program identity and prospective review.

## 2026-08-20 — Use symbol-specific quote costs and daily regulatory fees

- Decision: freeze Normal at each symbol's p75 adverse half-spread, Stress A at p95, and Stress B at p99. Round each selected rate upward to 0.01 basis point. Use one, two, and three five-minute fill-delay bars respectively. Keep one bar in the exact zero-cost diagnostic. Apply SEC, TAF, and CAT by their published daily aggregation and cent-ceiling rules. Derive the New York account day from aware execution timestamps and group TAF partial fills under one capped trade identity. Assume zero brokerage commission only for a direct Alpaca retail account without partner or Elite fees.
- Context: 80,399 causal SIP observations show different SPY and QQQ spread distributions. The generic `CostModel` cannot represent symbol-specific spread cost or account-day fees, and changing it would alter closed evidence.
- Consequences: model `intraday-execution-cost-model-001-v1` is valid only for retail-sized SPY/QQQ orders without material impact. A new Intraday Exposed 002 boundary must deduct daily fees before carrying equity into the next session and bind the model fingerprint in every result. Legacy runners remain unchanged. A different account fee arrangement invalidates the model instead of changing it after strategy results.
- Revisit when: official fees change before PAPER use, the account arrangement differs, or execution evidence supports depth, impact, latency, price improvement, or partial-fill modeling. Do not revise this model after Intraday Exposed 002 observes a strategy result.

## 2026-08-20 — Preserve crossed SIP states without using negative spreads

- Decision: close calibration plan v1 after its first SIP probe failed raw `ask >= bid` validation, then use a separate v2 plan and runtime identity. V2 retains every raw quote in provider/page order. Each one-second grid point inspects the latest unique raw state and excludes it when stale, one-sided, zero-size, or crossed; it never backfills an older eligible quote. Locked states remain eligible at zero spread. Every symbol-window still requires 99% eligible-grid coverage.
- Context: the v1 probe found 3 transient $0.01 crosses among 112,133 QQQ updates. Official UTP and CTA specifications permit crossed national BBO states, and regular condition `R` does not prohibit them. No dataset or strategy result existed when v1 stopped.
- Consequences: v1 plan and quarantine stay immutable. V2 plan SHA-256 is `67dc2a2155a91f5ab26395a4c3f34457ebcb6e1813f95f7e02c642129c9db546`; its separate `intraday-execution-calibration-001-v2` root cannot reuse v1 feed or dataset state. A create-only marker blocks later IEX fallback after any SIP data. The analysis reports raw market-state counts and grid exclusions instead of treating a negative spread as execution cost.

## 2026-08-20 — Calibrate intraday costs before new strategy research

- Decision: freeze one strategy-independent SPY/QQQ quote sample before acquisition. Select the first XNYS session on or after the 15th of each exposed month through May 2026, add every early close, and sample five fixed ten-minute time windows on a one-second causal grid. Prefer SIP; fall back to IEX only on an entitlement HTTP 403 and label it as venue-only evidence.
- Context: Intraday Exposed 001 charged 5 bps slippage and 1 bp commission on every fill without quote evidence or SEC, TAF, and CAT fees. Its empty cohort left the planned June range unread by that runner.
- Consequences: plan SHA-256 `7f762cb4195b406c8b86197bc02f36e562d65af559f8ae1c0070ce05a40d9e38` excludes June, V3, candidate timestamps, and strategy returns. A metadata-only audit reserves June once for Intraday Exposed 002; no June read is allowed before simultaneous cohort and controlled-plan freeze. Quote artifacts are content-addressed and grant no holdout, paper, broker-write, or live authority.
- Revisit when: quote validation fails, SIP entitlement differs, official fees change before model freeze, or an independent reviewer rejects the method. Do not change this plan after a quote is returned; create a new version.

## 2026-08-02 — Standalone typed Python package

- Decision: use Python 3.12+, a `src` layout, uv, ruff, mypy, and pytest.
- Context: the repository starts empty and needs a small inspectable base.
- Alternatives: a large trading framework or notebook-first layout.
- Reasoning: explicit modules keep system assumptions testable without adopting a framework's hidden semantics.
- Consequences: the project owns its core behavior; more code arrives only with a milestone need.
- Revisit when: a component has a measured need that a mature library meets without becoming authoritative.

## 2026-08-02 — Standard-library boundaries first

- Decision: use frozen dataclasses, `Decimal`, canonical JSON, argparse, and SQLite. Store the initial fixture dataset as canonical JSON Lines.
- Context: M0 and the safe M1 slice need deterministic evidence without a large runtime dependency.
- Alternatives: Pydantic, Click, SQLAlchemy, and Parquet/PyArrow immediately.
- Reasoning: standard-library types cover the current validated boundaries and make bootstrap setup smaller.
- Consequences: JSON Lines is not the long-term columnar research format; manifests isolate storage format and schema versions.
- Revisit when: real market-data volume makes columnar scans material; adopt Parquet/PyArrow before the Alpaca archive grows.

## 2026-08-02 — Content-addressed immutable datasets

- Decision: derive dataset directories from a SHA-256 fingerprint of the immutable version envelope: provider, request, adjustment policy, processing versions, raw artifact hash, and canonical normalized-bar fingerprint. Write artifacts atomically; an exact re-import returns the existing version.
- Context: evidence must not be silently overwritten and identical inputs must reproduce.
- Alternatives: mutable named files or database blobs.
- Reasoning: content addressing makes deduplication, integrity checks, and catalog reconstruction direct. Binding stable metadata prevents identical bars from different providers or requests from sharing one manifest.
- Consequences: corrected data becomes a linked version; the normalized-bar fingerprint remains separate so experiments can verify exact inputs. Retrieval time does not change the version identity.
- Revisit when: remote object storage requires a different atomic publication protocol.

## 2026-08-03 — XNYS calendar for session completeness

- Decision: use `exchange-calendars` with the XNYS calendar for expected daily sessions.
- Context: weekday checks accept U.S. market holidays as valid bars.
- Alternatives: a weekday-only rule or a hand-maintained holiday list.
- Reasoning: the maintained calendar captures holidays and shortened-session schedules without duplicating dates in this repository.
- Consequences: calendar version is part of the locked environment; missing expected sessions reject a dataset.
- Revisit when: a point-in-time calendar policy or multi-venue universe requires explicit calendar ownership.

## 2026-08-03 — Read-only Alpaca HTTP boundary

- Decision: use a small stdlib `urllib` adapter for historical bars and keep credentials at the CLI environment boundary.
- Context: M1 needs provider access but must not introduce broker authority or make an SDK authoritative.
- Alternatives: `alpaca-py` or direct broker integration.
- Reasoning: the endpoint is narrow, pagination is explicit, and the adapter is easy to mock and keep read-only.
- Consequences: endpoint response mapping is owned and tested here; later broker execution remains a separate module.
- Revisit when: paper execution needs broker functionality that cannot be isolated behind the same provider boundary.

## 2026-08-03 — Next-bar fill semantics for M2

- Decision: signals generated after a completed bar can first fill on the next available bar for that symbol, using its open plus conservative basis-point costs.
- Context: using the signal bar's close creates an optimistic execution assumption and can hide lookahead.
- Alternatives: same-bar close fills or a third-party backtesting engine.
- Reasoning: the rule is explicit, deterministic, and keeps core assumptions owned by this repository.
- Consequences: the final signal can be rejected for lack of a future fill; event, order, trade, and equity ledgers retain the timestamps.
- Revisit when: intraday data and a reviewed latency/session model support more detailed event scheduling.

## 2026-08-04 — Reports expose benchmarks without a hidden score

- Decision: reports list each baseline and expose excess return versus cash; they do not collapse results into a qualification score.
- Context: benchmark context is needed before interpreting a backtest, while aggregate scores can hide catastrophic weaknesses.
- Alternatives: a single composite rank or a report containing only the selected strategy.
- Reasoning: visible per-baseline metrics preserve the evidence needed for later qualification gates.
- Consequences: report consumers must compare multiple fields; qualification remains a separate M3 authority.
- Revisit when: a reviewed qualification policy defines explicit disqualifying gates and report schema requirements.

## 2026-08-04 — SQLite experiment lifecycle is authoritative

- Decision: record every campaign candidate in SQLite before execution and move it through guarded pending, running, completed, or failed states.
- Context: files alone cannot distinguish a crash from completion or enforce search-volume accounting.
- Alternatives: report-directory discovery or an in-memory job queue.
- Reasoning: SQLite transactions provide a small durable registry, explicit search budgets, and restart-safe state without a service dependency.
- Consequences: stale running experiments become failed evidence; completion cannot overwrite a failed or completed record. Each walk-forward fold and cost or delay variant consumes its own candidate, links to its parent, and remains visible in comparison reports even when it fails.
- Revisit when: concurrent distributed workers exceed SQLite's measured write capacity.

## 2026-08-04 — Holdout access requires a logged event

- Decision: ordinary reads hide holdout metrics; completed holdouts require a unique reviewer/reason event before metrics can be read or qualification recorded.
- Context: repeated holdout inspection turns the holdout into development data.
- Alternatives: filesystem naming conventions or an honor-system command flag.
- Reasoning: registry-enforced access makes the protected transition explicit and auditable.
- Consequences: holdout creation and evaluation use a separate controlled code path; routine experiment CLI excludes holdout creation.
- Revisit when: remote authorization and immutable external audit storage replace the local registry.

## 2026-08-02 — Universe provenance is part of dataset identity

- Decision: define fixed-universe membership as sourced time intervals and bind the universe ID and content fingerprint into dataset versions, correction lineage, and experiment records.
- Context: a symbol list alone cannot show whether every instrument was available for the full research range, and a mutable universe name cannot reproduce the exact membership rule.
- Alternatives: keep one unsourced symbol list, infer membership from available bars, or record only the universe name.
- Reasoning: an explicit interval check rejects incomplete or inception-crossing requests before acquisition, while the fingerprint preserves the exact reviewed definition used by a sealed dataset.
- Consequences: imports must include exactly the full-range members; changing membership creates a separate dataset lineage even when the bars match. The first format permits one interval per symbol.
- Revisit when: exits, re-entry, symbol changes, or a larger universe require multiple intervals or a dedicated membership source.

## 2026-08-02 — Qualification metrics use complete sessions

- Decision: calculate drawdown and qualification metrics from the last equity point in each daily session while retaining every per-symbol ledger point.
- Context: processing five same-timestamp ETF bars creates intermediate equity states that depend on symbol order and can report a false intraday drawdown.
- Alternatives: treat every symbol event as a return period or discard the detailed equity ledger.
- Reasoning: daily strategies need daily qualification periods, while the full ledger remains useful for accounting and debugging.
- Consequences: report schema v2 adds 252-session zero-rate Sharpe and volatility, gross exposure, session and instrument profit concentration, and SPY up/down-regime returns. Earlier campaign metrics remain immutable evidence under their original schema.
- Revisit when: intraday data requires an explicit event-time return and benchmark policy or a reviewed nonzero reference-rate series.

## 2026-08-03 — Qualification evidence uses explicit registry roles

- Decision: commit a strict evidence manifest that names each base, benchmark, cost, delay, and parameter-neighbor experiment used for qualification aggregation.
- Context: the first campaign summary derived gate metrics by hand, which could explain results but could not safely authorize holdout access.
- Alternatives: infer roles from experiment names or accept caller-supplied aggregate metrics.
- Reasoning: explicit IDs make the evidence set reviewable, while registry checks bind every value to a completed validation record, its parent, period, strategy, dataset, universe, parameters, cost model, and execution model.
- Consequences: qualification evaluation writes a content-addressed report and stops on missing or inconsistent records. Adding a candidate or sensitivity role requires a reviewed manifest change.
- Revisit when: a typed campaign planner records these roles at candidate creation and can generate the same manifest without weakening review.

## 2026-08-03 — Holdout creation consumes stored qualification authority

- Decision: replace caller-supplied holdout approval with a stored, one-time authorization built from approved and passing registry evidence.
- Context: `create_experiment` accepted a boolean that could bypass the intended qualification boundary.
- Alternatives: keep the boolean behind a CLI flag or trust a report file supplied by the caller.
- Reasoning: rebuilding evidence before authorization binds the decision to current registry records. Storing the candidate specification lets one SQLite transaction verify the holdout and consume its authority.
- Consequences: a holdout must match the qualified strategy, parameters, models, dataset, universe, parent candidate, and post-validation period. One candidate, manifest, proposal, and source experiment set authorizes one holdout even when later bookkeeping changes the report fingerprint. One completed holdout permits one logged metrics read.
- Revisit when: authorization moves to a remote reviewer service with independent identity and immutable audit storage.

## 2026-08-03 — Holdout data reads follow authorization consumption

- Decision: create and claim the exact holdout record before reading market data, then use a Parquet predicate to load only its inclusive timestamp range. Store metrics only in the registry and do not write a holdout report.
- Context: stored authorization blocked ordinary holdout creation, but the full-dataset loader would expose earlier and later rows and ordinary runner outputs would bypass the logged metrics-read event.
- Alternatives: validate the full dataset before consuming authorization, pass preloaded bars to the runner, or write a hidden report file.
- Reasoning: authorization-first range loading keeps unauthorized code from seeing holdout rows and keeps completed metrics behind one audited read boundary.
- Consequences: catalog and manifest metadata can be checked before consumption, but Parquet and simulation errors consume the authorization and remain failed evidence. Range validation checks identity, bounds, symbols, and complete XNYS sessions without recomputing the full dataset fingerprint.
- Revisit when: encrypted remote storage or an external execution service can enforce the same boundary and retain an independent audit log.

## 2026-08-03 — Cataloged research reads only its experiment range

- Decision: make the cataloged training and validation runner load only the inclusive period recorded in its experiment specification.
- Context: the earlier CLI loaded and fingerprinted the full normalized dataset before filtering bars for simulation. A dataset that extended past validation could therefore expose later data to an ordinary research process.
- Alternatives: keep the full read as an integrity check, split each date range into a separate dataset, or rely on callers not to inspect the extra rows.
- Reasoning: a Parquet predicate enforces the experiment boundary while the catalog and stored manifest still bind dataset and universe provenance. Range checks reject missing symbols or XNYS sessions.
- Consequences: the runner cannot recompute the normalized fingerprint for the full dataset without violating the read boundary. Full artifact validation remains a separate data-management operation, and direct in-memory tests may still supply a complete fingerprinted bar set.
- Revisit when: manifests include independently verifiable partition fingerprints or storage enforces row-level authorization.

## 2026-08-03 — Portfolio strategies decide after complete sessions

- Decision: give multi-symbol strategies a separate backtest method that receives one complete session and immutable per-symbol history through that close. Validate the full long-only target set atomically and fill accepted targets no earlier than the next configured bar for each symbol.
- Context: the per-symbol callback rejects cross-symbol targets and would make a portfolio rank depend on which symbol happened to run last. The failed long-horizon training campaign also showed a need to design allocation and turnover across the full portfolio.
- Alternatives: permit cross-symbol targets from one bar callback, choose one symbol as the session trigger, or let each target pass validation on its own.
- Reasoning: an explicit session boundary removes symbol-order lookahead, while atomic validation prevents part of an invalid allocation from trading. A total weight cap preserves the existing unlevered long-only model.
- Consequences: portfolio backtests reject incomplete symbol sessions and nonempty target sets that do not cover the full session universe. They canonicalize target order, execute reductions before buys, keep one decision record per session, and use the existing cost, order, trade, equity, and metrics model. This adds no paper or live execution authority.
- Revisit when: intraday event time, multiple venues, shorting, leverage, or partial portfolio acceptance has a reviewed data and risk model.

## 2026-08-03 — Validation trade evidence spans the campaign

- Decision: sum executed fills across all predeclared base-validation folds for the proposed trade-count gate instead of requiring the threshold in every fold.
- Context: the original 100-fill minimum in each annual fold structurally excluded monthly portfolio strategies and treated fills as if they were independent return observations.
- Alternatives: keep the per-fold floor, lower it for selected strategy families, or add a new backtest metric that requires rerunning immutable evidence.
- Reasoning: one campaign-wide rule applies to every strategy family and reuses recorded fill counts. Existing return, Sharpe, drawdown, regime, and concentration gates retain per-fold evidence checks.
- Consequences: the proposed threshold remains 100, but its aggregate metric and proposal fingerprint change. Existing immutable reports remain historical evidence; reevaluation creates new content-addressed reports. This decision does not approve any gate or revive a rejected candidate.
- Revisit when: execution-capacity analysis or a reviewed effective-sample-size metric can replace raw fill count.

## 2026-08-03 — Qualification gates v1 approved

- Decision: approve all 17 thresholds in `qualification-gates-v1` without changing their values or rationales.
- Context: the user reviewed the gates' role and explicitly approved them after the trade-count aggregation received its separate review.
- Alternatives: leave the policy unapproved or revise one or more thresholds before approval.
- Reasoning: the visible disqualifying gates cover validation stability, benchmark performance, risk, concentration, execution sensitivity, parameter sensitivity, regime coverage, activity, and search volume. Approval locks the rules before another candidate campaign.
- Consequences: passing evidence can authorize one exact holdout run. Existing moving-average and momentum evidence becomes formally rejected, relative strength remains stopped before validation, and no holdout is authorized. Future gate changes require a separate human-reviewed change and cannot accompany strategy changes.
- Revisit when: new evidence exposes a gate defect or the research, data, or execution model changes materially.

## 2026-08-03 — Sealed training plans preregister exact candidates

- Decision: load future official training campaigns from strict, fingerprinted plan files and atomically preregister every candidate before execution.
- Context: numeric campaign budgets preserved search count but did not bind the claimed predeclared IDs, parameters, dates, provenance, parents, or models.
- Alternatives: continue using Markdown plans and CLI flags, or build full automated candidate generation.
- Reasoning: a stored canonical plan makes the current manual workflow enforceable without expanding into M6 automation.
- Consequences: `training-campaign-plan-v1` is training-only, requires explicit parameters, exact budget use, default conservative costs, and next-bar fills. Planned runs accept only a stored candidate ID. Historical campaigns remain legacy evidence and are not rewritten.
- Revisit when: a candidate passes training and needs a reviewed validation-plan schema or sensitivity models.

## 2026-08-03 — Qualification accepts only controlled runner evidence

- Decision: mark runner-owned research completions as `controlled-run` and require each qualification source to carry that provenance plus exactly one report location and SHA-256 report fingerprint.
- Context: manual completion accepted caller-entered metrics and optional artifacts, while qualification trusted any completed validation record with matching relationships.
- Alternatives: remove manual lifecycle commands, trust sealed-plan membership alone, or re-run every source during qualification.
- Reasoning: a registry provenance field closes the shared evidence path without deleting operational history or coupling qualification to market-data reads.
- Consequences: manual and migrated legacy records remain readable but cannot qualify or authorize holdout access. Existing historical rows keep null provenance. Qualification gates and strategy behavior do not change.
- Revisit when: reports move to remote immutable storage or artifact attestations replace local registry trust.

## 2026-08-03 — Complete the bootstrap baseline set without search

- Decision: define mean reversion as long exposure when the close is below its trailing moving average, and define volatility-targeted exposure as a long-only weight capped at one and scaled inversely to trailing annualized volatility.
- Context: the bootstrap required both baselines, but the implemented suite omitted them while later portfolio families were evaluated.
- Alternatives: treat later volatility-balanced allocation as the same baseline, add threshold or band searches, or defer both to automated research.
- Reasoning: two fixed, inspectable rules complete the requested system checks without parameter optimization or a new backtest boundary.
- Consequences: both strategies use existing next-bar fills, split exposure across multi-symbol datasets, fail on zero realized volatility, and remain unqualified. No campaign or protected control changes.
- Revisit when: a reviewed research plan justifies bands, volatility forecasts, cash-rate assumptions, or portfolio-level volatility targeting.

## 2026-08-03 — Paper execution uses one transactional authority

- Decision: store M4 paper authorization, intent, risk, order, broker-event, reconciliation, emergency, and hash-chain journal state in one SQLite database. Reserve pending risk capacity, a deterministic client order ID, and one submitter atomically, then recheck all external guards immediately before a paper-only network call.
- Context: retries, crashes, stale snapshots, and broker drift can turn a valid strategy target into duplicate or unsafe orders when authorities use separate mutable state.
- Alternatives: separate databases per component, broker state as the local source of truth, or direct strategy-to-adapter calls.
- Reasoning: one transaction closes the risk-to-order race while explicit component interfaces preserve authority separation. Reconciliation and client-ID lookup handle uncertain submissions without blind retries.
- Consequences: no broker writer can operate without an exact immutable paper authorization, paper mode and endpoint, active reviewed limits, fresh snapshots, clean reconciliation, and clear emergency state. Broker evidence stores only sanitized normalized fields. Unknown submit or cancel results require lookup and reconciliation before retry. Paper results remain simulation evidence, not live-execution validation.
- Revisit when: measured concurrency, remote durability, or independent service deployment requires a database-backed event service without weakening atomic guards.
## 2026-08-03 — Stable reconciliation is a three-sample reviewed interval

- Decision: emergency-clear readiness uses the latest three distinct clean adapter-attested reconciliation records for one baseline, with each comparison and completed observation separated by the explicit positive stability interval in `RiskLimits`.
- Context: one clean read can capture a transient broker state and must not enable paper authority.
- Alternatives: one sample, two samples, a fixed global delay, or an operator-supplied delay outside the reviewed risk fingerprint.
- Reasoning: three consecutive samples expose a repeated state without adding a scheduler, while binding the interval into reviewed limits prevents a caller from shortening it at clear time.
- Consequences: any dirty record among the latest three resets readiness; the latest state must remain fresh at assessment. Readiness is read-only and does not clear emergency state.
- Revisit when: measured paper polling cadence or broker consistency data supports a stricter reviewed rule.

## 2026-08-03 — Approved risk decisions reserve capacity atomically

- Decision: an approved risk decision creates one immutable reservation for cash, gross exposure, order notional, and order count in the same SQLite transaction; active reservations are included in later evaluations until their bound expiry.
- Context: a risk approval without durable pending capacity can be duplicated across workers or restarts before an order lifecycle exists.
- Consequences: rejected decisions remain evidence, approved decisions cannot exist without a matching reservation, and reservation release waits for the reviewed forward-only order lifecycle slice.
- Revisit when: order submission, fill, cancellation, and reservation-release states are implemented and independently reconciled.

## 2026-08-03 — Filled orders retain capacity until reconciliation

- Decision: cancellation or rejection with zero cumulative fill releases reserved capacity atomically with the terminal local order transition. Any positive fill retains its reservation until reconciliation proves the resulting position.
- Context: releasing a filled order immediately would allow another decision to reuse capacity while portfolio snapshots may still show the pre-fill state.
- Consequences: zero-fill cancellation and rejection free capacity without a broker-position change. Partial or full fills retain capacity until normalized broker events and reconciliation can replace the reservation with verified position exposure.
- Revisit when: later complete reconciliation can bind a verified expected-position generation to settled broker state.

## 2026-08-03 — Broker evidence applies state or disables execution

- Decision: one normalized broker event and its forward local order transition share a transaction; identity, quantity, sequence, or local-state conflicts restore persistent emergency disable and reject the event.
- Context: storing valid evidence without applying it leaves local state stale, while applying an invalid or out-of-order event can hide drift or free capacity incorrectly.
- Consequences: accepted events are exact-idempotent, zero-fill cancellation and rejection release capacity, positive fills remain reserved for reconciliation, and raw broker responses never enter the execution database.
- Revisit when: polling and streaming event sources both exist and need one reviewed precedence rule.

## 2026-08-03 — A missing exact lookup is evidence, not retry authority

- Decision: persist a sanitized Alpaca-paper 404 only from the production exact-client-order lookup path and only for a local `submission-unknown` order. The record does not change order state or release capacity.
- Context: a broker can return a transient or stale negative lookup after an unknown submission outcome.
- Consequences: the result remains immutable historical evidence. Any future retry assessment must bind it to later full clean reconciliation; no retry or broker writer exists.
- Revisit when: observed paper behavior supports a stricter negative-confirmation rule.

## 2026-08-03 — Fill evidence keeps cumulative economics

- Decision: normalized broker events with positive cumulative filled quantity must include a positive finite cumulative average fill price. Later events cannot change price at the same quantity or reduce cumulative gross notional.
- Context: quantity alone cannot support deterministic incremental expected-position and cash-impact calculations.
- Consequences: exact lookups retain enough gross fill economics for the next expected-state slice. Fees and account-wide equity or buying power remain unknown, so filled capacity is not released.
- Revisit when: authoritative fee evidence or a reviewed post-fill accounting model exists.

## 2026-08-03 — Expected positions advance from accepted fills

- Decision: an explicit reconciliation baseline can bind accepted cumulative fill increments to immutable sorted position checkpoints in the same transaction as broker evidence and local order state. Each checkpoint links its prior fingerprint and uses the immutable local order for symbol and side.
- Context: broker events can prove signed whole-share changes but cannot derive account-wide cash, equity, buying power, or fees.
- Consequences: expected position lineage is replayable and read-only. Bare broker evidence does not gain lineage later, negative positions fail closed, and any positive fill keeps its capacity reservation. Full portfolio reconciliation and filled-capacity release remain separate.
- Revisit when: a later complete adapter-attested snapshot can prove the expected position generation and settled open-order state.

## 2026-08-03 — Position settlement is separate from account accounting

- Decision: immutable position-settlement evidence binds the current expected-position lineage head to one later complete production-attested paper snapshot with exact positions, no open or nonterminal local orders, fresh observations, and clear emergency state.
- Context: a fill lineage can predict shares but cannot derive fees, marks, cash, equity, or buying-power treatment.
- Consequences: the proof records the observed snapshot and its adapter attestation but compares only position and order settlement. It does not create a local portfolio snapshot, change full reconciliation, or release capacity.
- Revisit when: a reviewed rule can replace pending reservations with fresh adapter-observed risk context without double counting or early reuse.

## 2026-08-03 — Settlement alone cannot release risk capacity

- Decision: settlement-capacity assessment is read-only and always blocks mutation while risk decisions accept caller-supplied context without durable adapter provenance.
- Context: releasing a positive-fill reservation against stale or fabricated cash, buying power, exposure, quote, or clock values could reuse capacity twice.
- Consequences: the assessment identifies exact positive-fill reservations and binds observed account values, but reports `context-provenance-missing` and changes no journal or release row. Filled capacity remains held.
- Revisit when: a production-attested snapshot-derived risk context also binds durable quote, clock, session, exposure, PnL, drawdown, limits, emergency generation, and settlement evidence.

## 2026-08-03 — Risk quotes and clock are separate attested inputs

- Decision: the production-only risk-input reader stores immutable normalized IEX latest quotes for the complete reviewed symbol set and the current NYSE `/v3/clock` response, bound to one fresh production-attested paper portfolio snapshot, paper authorization, and exact risk configuration.
- Context: caller-supplied quote and clock values cannot support safe reservation reuse or later paper admission.
- Consequences: fixed-origin GET-only evidence keeps bid, ask, sizes, provider times, observations, session phase, adapter version, and portfolio authority. It grants no risk approval and changes no capacity.
- Revisit when: durable strategy PnL, drawdown, quote-pricing policy, and reservation-set evidence can derive the full `RiskContext` without caller financial inputs.

## 2026-08-03 — Long-only risk exposure uses the IEX ask

- Decision: derive current symbol notional and gross long exposure from the complete attested IEX quote set using each symbol's ask price.
- Context: the conservative basis avoids understating long exposure without trusting caller prices.
- Consequences: the deterministic valuation can overstate liquidation value. It does not supply a side-aware execution quote or replace broker equity, cash, buying power, or strategy performance evidence.
- Revisit when: the execution envelope permits shorts or an approved risk model requires separate liquidation and acquisition prices.

## 2026-08-03 — Execution-price risk checks are side-aware

- Decision: `RiskContext` carries the current whole-share quantity and both bid and ask. Risk evaluation uses the ask for increases and the bid for reductions; long target exposure remains ask-valued.
- Context: one quote field could let a sell pass its price-deviation gate on a favorable ask even when the executable bid was materially worse.
- Consequences: crossed quotes fail construction. Quantity-target order notional uses the selected side, while projected long exposure uses the conservative ask.
- Revisit when: a later execution envelope adds short sales, limit-price placement, or fractional shares.

## 2026-08-03 — Daily loss uses attested account equity change

- Decision: Alpaca paper snapshot attestation v2 retains the positive `last_equity` account field. Daily PnL is the current attested equity minus that prior-close equity.
- Context: `RiskContext.daily_pnl` must not come from a caller, and account daily loss is distinct from per-strategy drawdown.
- Consequences: the value is derived read-only from immutable adapter evidence and binds the snapshot and attestation fingerprints. Version-1 attestations remain valid but cannot produce daily PnL evidence.
- Revisit when: the broker changes the account contract or reviewed policy requires a different daily-loss session boundary.

## 2026-08-03 — Risk decisions bind the temporal active reservation set

- Decision: inside the risk-decision transaction, derive the active reservation set from immutable rows whose reservation time is at or before evaluation, expiry is after evaluation, and release is absent or later than evaluation. Replace caller pending-capacity totals and fingerprint the exact set.
- Context: caller totals can omit a reservation or erase capacity with a timestamp from the wrong point in time. A later release must not change an earlier evaluation.
- Consequences: risk decisions now bind reservation IDs, reservation fingerprints, aggregate cash, gross exposure, order notional, and count. Filled capacity remains reserved until an effective release event.
- Revisit when: the complete attested risk context can consume this set alongside strategy drawdown and settlement evidence.

## 2026-08-03 — Strategy drawdown starts from reviewed allocated capital

- Decision: require a positive strategy-capital allocation in each reviewed risk configuration and bind one immutable strategy-equity baseline to the exact paper authorization and flat reconciliation baseline.
- Context: account equity drawdown can hide one strategy's loss behind another strategy's gain, while the bootstrap defines no strategy-capital allocation value.
- Consequences: the allocation changes the risk-configuration fingerprint and has no production default. The baseline binds account, strategy identity and version, allocation, operator, reason, and time. It grants no PnL, peak, drawdown, risk approval, or capacity authority.
- Revisit when: immutable fills, strategy cash flows, fees, and quote marks can advance strategy-equity checkpoints.

## 2026-08-03 — Strategy equity uses fill replay, cost reserve, and bid marks

- Decision: derive immutable strategy-equity checkpoints by replaying cumulative accepted-fill notional, subtracting an explicit reviewed basis-point cost reserve on buys and sells, and marking settled long positions at production-attested IEX bids.
- Context: account equity cannot isolate one strategy, cumulative average fill price is not an incremental cash ledger, and the current broker evidence has no authoritative fee field.
- Consequences: `RiskLimits` requires a nonnegative strategy fill-cost value with no production default. Each checkpoint requires the latest settlement proof, complete fresh bid evidence, and prior peak lineage. The reserve is policy, not broker fee evidence. Derived drawdown grants no risk approval or capacity authority.
- Revisit when: authoritative broker fee evidence can replace or reconcile the reserve, or the execution envelope permits shorts.

## 2026-08-03 — Complete risk context is derived in one read transaction

- Decision: derive every `RiskContext` field from verified journaled evidence inside one SQLite read transaction and return a fingerprinted provenance proof.
- Context: independently valid account, quote, clock, daily-PnL, strategy-drawdown, settlement, reservation, authorization, limits, and emergency values can still describe different moments or authorities.
- Consequences: callers supply only authorization, symbol, reviewed limits, and evaluation time. The builder writes nothing and grants no risk approval or capacity authority. One-minute order activity comes from journaled reservations, including completed attempts, while active reservation capacity uses exact temporal membership.
- Revisit when: the risk-decision transaction replaces its legacy caller-supplied context with this derivation under an immediate write lock.

## 2026-08-03 — Risk decisions derive attested context under their write lock

- Decision: expose only a risk-decision entry point that derives the complete attested context inside the same immediate transaction as decision and reservation persistence.
- Context: a read-only proof can become stale before a later write, while caller financial inputs cannot establish provenance.
- Consequences: callers provide only intent, authorization, reviewed limits, and evaluation time. Decisions bind the context-provenance fingerprint. Exact replay excludes its own reservation and returns the original receipt; a changed second decision for one intent fails closed. Direct context injection remains private test scaffolding.
- Revisit when: settled filled reservations can be replaced atomically by the same current attested context without double counting.

## 2026-08-03 — Settled positions replace exclusive pending capacity atomically

- Decision: release positive-fill reservations only when the same immediate transaction derives a complete attested context that matches the current settlement proof, emergency generation, and exact exclusive active reservation set.
- Context: retaining settled reservations double counts exposure already present in the attested portfolio, while releasing them from settlement evidence alone can reuse capacity against stale or incomplete risk inputs.
- Consequences: later order mutations, stale evidence, unrelated active reservations, and changed replay fail closed. Individual capacity releases and one immutable summary proof share the transaction. The release grants no broker-write authority.
- Revisit when: multiple concurrent settled batches must share one account without requiring an exclusive active reservation set.

## 2026-08-03 — Paper submission preflight accepts quantity targets only

- Decision: before a quantity-target order enters `submitting`, rederive the complete attested context and reevaluate every risk gate under the same immediate transaction as the single-submitter claim. Require the staged delta to match current shares and current economics to fit within the existing reservation.
- Context: staging binds an intent and reservation but does not prove that an arbitrary whole-share delta matches a weight target or a later portfolio state.
- Consequences: preflight binds paper mode, fixed origin, authorization, limits, intent, delta, submitter, and current risk proof. Weight-target submission remains blocked. No broker transport exists.
- Revisit when: policy defines deterministic weight-to-share rounding and its reservation treatment.

## 2026-08-03 — Submission preflight is the one-shot attempt marker

- Decision: let only the process that creates a paper submission preflight invoke the fake transport. Treat every existing preflight as a prior attempt that requires lookup and reconciliation before any retry.
- Context: an idempotent submitter claim cannot distinguish a harmless read replay from a duplicate external call after a crash.
- Consequences: valid normalized fake evidence advances through the broker-event authority. Transport or evidence failure enters `submission-unknown`. Restart and concurrent replay cannot invoke the injected transport twice. No HTTP transport exists.
- Revisit when: the production paper adapter can bind its exact POST attempt and sanitized outcome to the same authority.

## 2026-08-03 — Paper order POST remains injected-only

- Decision: construct and validate the exact Alpaca paper `POST /v2/orders` contract behind a mandatory injected transport with no production fallback.
- Context: request and response semantics need end-to-end coverage before repository policy permits any broker write.
- Consequences: tests exercise the supported whole-share day-market envelope, fixed origin, normalized acknowledgement, sanitized timeout, and one-shot outcome handling without contacting Alpaca. Production paper and all live calls remain impossible.
- Revisit when: cancellation recovery, cancel-all evidence, operations runbooks, an active reviewed risk configuration, and explicit broker-write enablement exist.

## 2026-08-03 — Cancellation mutation state stays separate from fill state

- Decision: store one immutable cancellation attempt per nonterminal order and separate unknown-outcome evidence without adding cancel states to the order lifecycle.
- Context: a cancel request can race with partial or full fills. Replacing broker order state with `canceling` would hide authoritative fill progress.
- Consequences: the attempt binds the latest broker event, authorization, operator, reason, paper origin, and time. Unknown outcome never retries or releases capacity. Later broker events remain authoritative and terminal state resolves the attempt.
- Revisit when: the injected cancellation adapter and lookup recovery can prove a richer mutation lifecycle without obscuring fills.

## 2026-08-03 — Cancel acceptance is not cancellation proof

- Decision: let only the creator of an immutable cancellation attempt call the injected fixed-origin single-order DELETE adapter. Treat an empty response as request acceptance, not terminal order evidence.
- Context: Alpaca can accept a cancel request while a fill or cancellation remains in flight, and a timeout cannot reveal whether the request arrived.
- Consequences: timeout or invalid response records unknown outcome. Existing attempts block repeat calls. Only later broker evidence can resolve the order and release eligible capacity. No production transport exists.
- Revisit when: production paper mutation authority and cancellation lookup recovery are reviewed together.

## 2026-08-03 — Cancel-all is a plan, not a bulk broker call

- Decision: store one immutable cancel-all snapshot of the exact sorted local nonterminal order set and its latest broker-event fingerprints. Do not use Alpaca's bulk cancellation endpoint.
- Context: one bulk response can hide partial acceptance, timeout, fills, and per-order unknown outcomes.
- Consequences: the plan grants no mutation authority. Each item must use the existing single-order attempt and resolution controls, preserving evidence and capacity per order.
- Revisit when: measured scale proves sequential single-order cancellation cannot meet an explicit emergency deadline.

## 2026-08-03 — Cancel-all progress is per order and restart-safe

- Decision: consume a cancel-all plan sequentially through separate one-shot attempt transactions that recheck each planned broker-event fingerprint.
- Context: the order state can change after planning, and a process can stop after any subset of external calls.
- Consequences: accepted, unknown, prior-attempt, and stale results remain distinct. Restart skips durable attempts, stale items make no call, and one failure does not erase other progress.
- Revisit when: measured cancellation latency requires bounded parallel workers with the same per-order invariants.

## 2026-08-03 — Cancellation resolution requires positive lookup provenance

- Decision: store immutable fixed-origin production exact-lookup provenance beside each successful normalized broker event and assess cancellation resolution read-only.
- Context: a bare broker event cannot prove that an exact lookup occurred after a cancellation attempt or its unknown outcome.
- Consequences: only the latest matching post-attempt lookup and local terminal state can report canceled, rejected, or filled resolution. The assessment grants no retry, broker-write, capacity, or emergency authority. A crash between event and provenance writes remains fail-closed and a later safe GET can complete the evidence.
- Revisit when: a reviewed recovery workflow needs a separately authorized mutation after complete reconciliation.

## 2026-08-03 — A readiness runbook cannot enable broker writes

- Decision: record every paper-write prerequisite, first-session check, abort condition, and recovery rule while keeping runtime write authority hard-coded off.
- Context: no candidate qualifies, no production risk values or mutation transport exist, and a checklist must not become an implicit enablement control.
- Consequences: the runbook makes missing authority explicit but changes no configuration, endpoint, credential, risk, order, or broker behavior. Each blocker requires a separate reviewed change; paper and live writes remain prohibited.
- Revisit when: a qualified candidate and reviewed production risk values exist and the explicit multi-control paper enablement boundary is ready for design review.

## 2026-08-03 — Paper-write activation and process opt-in are separate controls

- Decision: store one immutable, expiring activation bound to exact reviewed authority and require a separate process opt-in naming its fingerprint and code commit. Revocation is append-only.
- Context: paper mode, credentials, authorization, or an environment flag alone must never create broker-write authority.
- Consequences: activation binds account, authorization, limits, code, fixed origin, operation scope, distinct approver and operator, attempt cap, emergency generation, and time. Assessment remains read-only, runtime write authority stays false, and no production transport exists.
- Revisit when: submission and cancellation can recheck both controls inside their one-shot attempt transactions.

## 2026-08-03 — Activation caps count exact bound attempts

- Decision: bind the activation ID and process opt-in fingerprint inside existing submission and cancellation attempt transactions, then count the exact pair across both journal event types.
- Context: global event counts cannot prove which activation authorized an attempt, and separate per-operation counts could exceed one activation-wide cap.
- Consequences: the count and insert share one immediate transaction. Existing unbound injected attempts remain compatible and do not count. Runtime code identity remains unverified, bound records expose no transport, and broker-write authority stays false.
- Revisit when: a reviewed runtime build-identity proof can replace the remaining explicit assessment blocker.

## 2026-08-03 — Runtime identity starts with an attested wheel

- Decision: build one wheel on `main`, bind its SHA-256 and package metadata to the exact 40-character source commit in a deterministic manifest, and request GitHub attestations for both artifacts from one fixed workflow.
- Context: an environment commit string, editable install, clean Git checkout, wheel metadata, or installed `RECORD` hashes cannot prove which reviewed workflow built an artifact.
- Consequences: ordinary CI validates wheel and manifest creation. The manual provenance workflow has only read, OIDC, and attestation permissions. GitHub run `30877972755` confirmed that the repository could not persist attestations while it was user-owned and private. After it became public, run `30882447856` persisted attestations for both artifacts. The workflow retains unsigned files for diagnosis but stays failed when attestation fails.
- Revisit when: the runtime verifier and first retained attested artifact exist.

## 2026-08-04 — Build verification requires both attested artifacts

- Decision: verify both the exact wheel and its strict manifest through GitHub CLI against the fixed repository, fixed signer workflow, and GitHub-hosted runner policy before constructing an immutable runtime build identity.
- Context: a manifest attestation authenticates its wheel digest, but verifying the named wheel too avoids relying on one indirect subject. Caller strings, command output, and artifact names alone are not authority.
- Consequences: missing files, unknown fields, wrong authority, digest mismatch, tamper, timeout, missing GitHub CLI, or either failed attestation blocks identity creation without exposing subprocess output. The proof remains read-only and does not yet bind installed files or remove the activation blocker.
- Revisit when: non-editable installation provenance and complete installed-file hashes can bind the running package to the verified wheel.

## 2026-08-04 — Installed runtime identity requires exact wheel files

- Decision: accept only a non-editable archive install whose `direct_url.json` SHA-256 names the verified wheel, whose wheel-owned installed files match both `RECORD` copies, whose package tree has no unexpected importable files, and whose loaded package and modules resolve inside that exact distribution.
- Context: an attested wheel does not prove that the running process loaded it. Installed metadata alone is mutable and editable or mixed-package imports can bypass the reviewed artifact.
- Consequences: missing, malformed, parent-escaping, mismatched, extra, mixed-origin, editable, or tampered evidence blocks installed identity creation. Installer-generated script and `__pycache__` rows remain outside the trusted file set. The check is read-only and does not protect against local mutation after it returns, verify dependencies, or grant paper-write authority.
- Revisit when: activation assessment can bind a fresh installed identity to its exact reviewed commit.

## 2026-08-04 — Runtime identity is bound inside paper-attempt transactions

- Decision: activation assessment accepts one installed runtime identity verified no more than five seconds earlier, requires its full source commit to match the activation and process opt-in, and binds its fingerprint into each new request-bound submission preflight or cancellation attempt under the existing immediate transaction.
- Context: verifying an installation without carrying that proof into the atomic attempt record leaves the code identity detached from the authority it checked.
- Consequences: a missing, stale, mismatched, future-dated, or invalid identity blocks new activation-bound attempts. Activation and process opt-in commits must be full lowercase Git SHA-1s. Legacy records without the field remain readable. The fingerprint is immutable evidence of the identity checked near creation, not a defense against later local file mutation or hostile local code. Runtime broker-write authority stays false and no production transport exists.
- Revisit when: a reviewed production paper transport can consume only complete bound evidence without creating implicit authority.

## 2026-08-04 — Exact process opt-in opens only the outer paper-write gate

- Decision: let `broker_writes_allowed` become true only in exact paper mode with both an activation fingerprint and full execution commit in the process request.
- Context: the production coordinator must become reachable without treating mode, credentials, or process configuration as transaction authority.
- Consequences: construction remains blocked without exact opt-in. Submission and cancellation still recheck durable activation, installed identity, risk context, emergency state, operation scope, and shared attempt capacity inside each one-shot transaction before transport.
- Revisit when: another paper operation needs a separately reviewed transaction-bound authority path.

## 2026-08-04 — Strategic allocation advances to protected holdout

- Decision: predeclare a 35% SPY, 25% QQQ, 25% IWM, 15% GLD, and 0% TLT allocation with a 21-session rebalance interval and 10- and 42-session neighbors.
- Context: the fixed ETF universe needed a low-turnover candidate whose allocation and search volume were fixed before controlled training and validation.
- Consequences: the base beat fixed-weight in all three validation folds and passed all 17 unchanged approved gates. One exact 2026 holdout completed with its metrics protected. This evidence grants no paper or broker-write authority.
- Revisit when: a separately approved one-time holdout review has recorded its result or new evidence invalidates the candidate.

## 2026-08-04 — Holdout review binds approved gates before access

- Decision: permit one holdout read only through an approved proposal bound to the exact holdout campaign, then persist the event ID, proposal fingerprint, gate observations, result, and review fingerprint.
- Context: the completed strategic-allocation holdout must not be exposed before its evaluation rules are approved, and a crash after access logging must not force an untracked second read.
- Consequences: unapproved or mismatched proposals fail before access. Exact replay can complete the same review; another event or changed reviewer or reason fails closed. The seven approved gates reuse the validation thresholds for return, Sharpe, drawdown, exposure, concentration, and turnover.
- Revisit when: the one-time review is complete or another holdout schema needs different approved metrics.

## 2026-08-04 — Strategic allocation passes protected holdout review

- Decision: record the strategic-allocation holdout as qualified after event `m3-sa-holdout-review-v1` applied all seven approved gates.
- Context: the one-time review observed 0.091569 total return, 0.990546 Sharpe ratio, 0.107254 maximum drawdown, 0.993060 average gross exposure, 0.196134 top-five-session profit share, 0.398111 top-instrument profit share, and 1.166143 turnover.
- Consequences: every gate passed and the stored review fingerprint is `5264274cdab7ad11cde9a87895acc09be81ddae1057fa227694b72ec731e6dfc`. This result permits later paper-authorization review but grants no risk, transport, activation, broker-write, or live authority.
- Revisit when: new evidence invalidates the candidate or a reviewed paper authorization expires.

## 2026-08-04 — Risk-input freshness bounds provider-clock skew symmetrically

- Decision: apply the reviewed snapshot-age limit to the absolute difference between provider and local observation timestamps.
- Context: production IEX quotes were about 3.12 seconds ahead of the local clock and failed before evidence persistence despite remaining within the 15-second freshness window.
- Consequences: quote and NYSE clock timestamps may lead or trail local observation only within the configured limit. Larger past or future differences fail closed. No broker-write authority changes.
- Revisit when: measured clock behavior needs a separate, stricter skew limit.

## 2026-08-04 — Flat checkpoints may refresh only before execution

- Decision: allow a new zero-state checkpoint to chain from the prior zero-state checkpoint while fresh flat settlement and risk-input evidence exist and no capacity reservation has ever been created for the authorization.
- Context: the initial checkpoint's observations expire after 15 seconds, so a one-shot checkpoint cannot support later startup assessment even when the account remains flat.
- Consequences: pre-trade readiness can refresh without inventing fills or resetting strategy state. Any fill-mode checkpoint or execution artifact permanently closes the flat refresh path.
- Revisit when: a reviewed session supervisor owns periodic pre-trade evidence refresh.

## 2026-08-04 — Long-only weights floor to whole shares at the ask

- Decision: convert each approved target weight to `floor(allocated capital * target weight / attested ask)` before creating a quantity intent.
- Context: paper submission accepts only exact whole-share quantities, while the qualified strategic-allocation candidate emits weights.
- Consequences: fractional cash remains uninvested, target notional cannot exceed its weight budget at the planning quote, and submission continues to reject raw weight intents. Risk preflight revalues the quantity at a fresh executable-side quote.
- Revisit when: odd lots, fractional shares, tax lots, or cash-allocation optimization receive separate policy.

## 2026-08-04 — Terminal replay recovery requires stable fill-derived state

- Decision: clear the former unchanged-terminal replay false positive only after two identical production exact-lookups, a later post-emergency lookup, and three stable production portfolio snapshots match fill-derived cash and expected positions.
- Context: the first 4-share SPY paper fill resolved exactly, but a second identical filled lookup was rejected before terminal self-replay support existed and set emergency generation 3.
- Consequences: another emergency reason, changed terminal economics, missing lookup provenance, open orders, position drift, cash drift, stale evidence, or an unstable sample blocks recovery. The clear binds its complete proof and grants no broker mutation. A later reviewed clear may precede settlement of an older confirmed fill; an active emergency still blocks settlement.
- Revisit when: sustained paper supervision owns a general incident-classified recovery workflow.

## 2026-08-04 — Expired filled reservations still receive settlement evidence

- Decision: permit settled-capacity release after a positive-fill reservation expires when the fresh attested portfolio contains the fill, the settlement and emergency generation match, the reservation remains unreleased, and no unrelated active reservation exists.
- Context: the first SPY fill required reviewed terminal-replay recovery longer than the reservation lifetime. Expiry removed pending capacity but left no immutable record that the filled reservation had settled into broker holdings.
- Consequences: expiry cannot block accounting completion or restore pending capacity. The release remains append-only, idempotent, and broker-free. Any missing fill, stale context, later order change, prior release, or unrelated active reservation fails closed.
- Revisit when: sustained supervision can settle fills within the reservation lifetime or concurrent settlement needs a broader account-wide proof.

## 2026-08-04 — Sustained observation starts read-only

- Decision: define a bounded paper observation campaign from one production-attested portfolio snapshot and record immutable healthy, drift, or sanitized read-failure samples without activation or broker mutation authority.
- Context: M5 needs measured continuity and disconnect evidence before a scheduler or recovery supervisor can make operational decisions.
- Consequences: the campaign fixes expected positions, account, maximum sample gap, and end time. Assessment reports current staleness, historical failure and drift counts, and the largest completed gap. Recovery samples never erase prior failures. No observation can submit, cancel, settle, clear emergency state, or approve risk.
- Revisit when: measured sampling behavior defines scheduler tolerances and the replay/shadow equivalence record needs shared campaign identity.

## 2026-08-04 — Equivalence compares immutable action plans

- Decision: bind one replay plan, one shadow plan, and paper actions derived from stored quantity intents under the active observation campaign, then retain exact mismatch reasons.
- Context: M5 needs replay, shadow, and paper comparison evidence without giving a comparison tool strategy, risk, or broker authority.
- Consequences: strict external plans bind their source, configuration, targets, and evidence fingerprints. The paper side is rederived from immutable intents. Strategy, source, configuration, or target differences remain append-only failed evidence. The comparison does not claim fill equivalence or approve execution.
- Revisit when: a scheduler-independent replay or shadow runner can emit the strict plan directly instead of handing the recorder a file.

## 2026-08-04 — The first observation timer stays outside the program

- Decision: use the operating system's task scheduler to call the one-shot observation command every 10 minutes from one exact attested runtime.
- Context: the first campaign needs timing and cold-process restart evidence, but no in-program daemon, broker authority, or remote state service.
- Consequences: the task can wake the computer from sleep and start missed work when available. It cannot run while the computer is off, and any late sample remains visible in the immutable gap evidence. The task expires with the campaign.
- Revisit when: a reviewed always-on host and durable remote state can replace the local task.

## 2026-08-04 — A VPS screen loop remains one external writer

- Decision: permit one GNU Screen session to call the one-shot observation command at a bounded interval, guarded by a local file lock, while keeping restart after a VPS reboot manual.
- Context: an always-on VPS removes dependence on a personal computer without adding an in-program daemon or systemd unit.
- Consequences: SSH disconnects do not stop sampling, but a VPS reboot does. Migration must stop the old writer before copying SQLite. Cleanup defaults to a preview and deletes only validated project-local data unless the operator also requests repository deletion. External broker, GitHub, backup, audit, and shell records remain outside its scope.
- Revisit when: automatic reboot recovery or remote state requires a reviewed service manager and monitoring design.

## 2026-08-07 — Intraday bars use XNYS bar-open timestamps

- Decision: support `1m` and `5m` immutable bars whose UTC timestamps label bar opens, with expected intervals derived from each actual XNYS regular-session open and close.
- Context: daily session dates could not represent multiple bars per session or prove holiday and early-close completeness.
- Consequences: dataset identity binds `bar-open-utc-v1` and `XNYS-regular-session-bars-v1`. Missing, duplicate, non-increasing, malformed, or out-of-session records reject the dataset and remain evidence. Daily labels and validation remain unchanged.
- Revisit when: quotes, trades, extended hours, partial bars, another venue, or a provider convention requires another versioned schedule.

## 2026-08-07 — Intraday replay observes completed bars before next-bar fills

- Decision: reuse the existing simulator with an explicit timeframe. An intraday bar becomes observable at open plus duration; decisions and order creation use that time, and fills use the next eligible same-symbol bar open after the configured whole-bar delay.
- Context: treating a provider bar-open label as the decision time would allow its completed high, low, close, and volume to influence the past.
- Consequences: contiguous next-bar fills may share the bar-close decision timestamp but never precede it. Daily behavior remains unchanged. Intraday diagnostics aggregate equity at each New York session end, while experiments, qualification, holdouts, paper execution, and broker authority remain daily-only.
- Revisit when: quote-based spread, latency, partial-fill, impact, or intraday qualification models receive separate review.

## 2026-08-08 — Day-trading replay flattens at the final eligible bar open

- Decision: add the explicit `XNYS-regular-session-flat-v1` policy. It limits delayed fills to one New York session, creates a zero-weight intent early enough to fill at the final validated bar open, rejects unsafe late entries, and fails if exposure or a pending order survives the session.
- Context: the generic intraday replay could carry a position or delayed order through a normal or early close. A close-price liquidation decided after the close would introduce lookahead.
- Consequences: flat-at-close decisions use only completed bars and respect the configured whole-bar delay. The last regular-session bar may mark the already-flat portfolio but cannot create another eligible fill. Daily replay and intraday diagnostics without the day-trading policy remain unchanged. Intraday experiment and qualification paths remain blocked.
- Revisit when: a reviewed auction, market-on-close, quote-latency, partial-fill, or halt model can replace the final-bar-open approximation.

## 2026-08-08 — Intraday research uses separate versioned evidence contracts

- Decision: store `intraday-experiment-v1` in the shared lifecycle registry, run only cataloged training or validation ranges, and emit `intraday-backtest-report-v1` plus research-only `intraday-qualification-evidence-v1`.
- Context: daily lifecycle and catalog primitives are reusable, but daily report, qualification, and holdout contracts do not bind timeframe, bar-open observability, flat-at-close policy, raw cost values, whole-bar delay, or intraday benchmarks.
- Consequences: existing daily records and interfaces remain unchanged. Intraday candidates bind a fixed campaign budget and ordinal, preserve failures, report zero-trade results, and expose sample, holding, exposure, cost, benchmark, concentration, session, cost-stress, and delay-stress evidence. The intraday evaluator cannot authorize holdout access, paper execution, broker writes, or promotion.
- Revisit when: production-scale sealed intraday campaign plans, a separately reviewed protected holdout, opening-range behavior, or M5C paper controls receive approval.

## 2026-08-08 — Initial intraday strategies remain fixed engineering baselines

- Decision: begin with cash, one-bar directional momentum, and a 12-bar moving-average trend over complete SPY/QQQ slices. Allocate at most one-half to each symbol, stay long-only and unlevered, and enforce `XNYS-regular-session-flat-v1`.
- Context: M5B needs deterministic system checks without broad search or claims of profitability.
- Consequences: the CLI exposes no strategy parameter override. Opening-range breakout, parameter optimization, shorting, leverage, extended hours, options, and autonomous generation remain deferred. Validation variants may change only preregistered costs, delay, or parameter-neighbor evidence and must retain parent lineage.
- Revisit when: reviewed campaign plans define bounded parameter neighborhoods or another fixed baseline adds enough evidence to justify its complexity.

## 2026-08-08 — The first intraday campaign reserves every base and stress run

- Decision: preregister `intraday-research-v1` with SPY/QQQ `5m` data, one six-month training window, three following two-month validation windows, the three fixed M5B baselines, and five candidates per strategy-period pair: base, increased cost, harsher cost, `+1` bar, and `+2` bars.
- Context: the first historical campaign must test chronological validation and research evidence without adding candidates or changing assumptions after results appear.
- Consequences: the strict plan fingerprint reserves all 60 ordinals, uses 5/1, 10/2, and 20/5 slippage/commission basis points with one/two/three-bar delays, and rejects parameter neighbors or any holdout, paper, broker-write, or live authority. No real run can start until independent read-only credentials produce four valid sealed datasets. A deterministic fixture proof remains ignored and is not campaign evidence.
- Revisit when: independent historical credentials are available, a data defect blocks the frozen windows, or a software defect requires a separately versioned campaign.

## 2026-08-12 — Final observation status preserves historical failures

- Decision: derive current health, completion, continuity, and final campaign result separately from immutable observations. A completed campaign passes only when its latest state is healthy and fresh, no completed sample gap exceeds the configured maximum, and no drift occurred.
- Context: Week 1 ended healthy after 1008 healthy samples and one recovered read failure, but two VPS reboots created a real gap of approximately 1030.755 seconds, reported as 1031 seconds, against the fixed 900-second limit. The old assessor exposed the gap but based its exit code only on current health.
- Consequences: a recovered read failure remains counted but does not alone fail the campaign because scheduled failure and recovery are M5 evidence. Historical drift and excess gaps remain final blockers after recovery. Existing databases need no migration or evidence change, and assessment grants no broker authority.
- Revisit when: a separately reviewed policy defines tolerated failure budgets or restart-safe supervision.

## 2026-08-12 — systemd supervises one verified read-only observation loop

- Decision: use one boot-enabled systemd service to run the packaged paper-observation supervisor from an exact project-local attested runtime. Pin the campaign, runtime artifacts, home, interval, GitHub host, and GitHub CLI directories in a generated unit; hold both current and legacy locks beside the execution store; keep Screen as an optional launcher for the same command. Migrate an old root-run deployment by changing ownership only on `.env`, the execution database and present SQLite sidecars, and both locks. Keep the project-local state parent root-owned and sticky and every runtime-build path root-owned and non-writable by the service.
- Context: GNU Screen survives SSH disconnects but not a host reboot. Week 1 proved that manual restart can breach the 900-second continuity limit. The old VPS store is root-owned, while the service must be unprivileged. GitHub CLI exposes one generic failure exit for remote attestation transport, absence, and rejection, so the caller cannot safely infer a permanent remote verdict from that code. A finite systemd start limit can permanently stop automatic retries after several transient failures; expiry of its interval does not restart the unit.
- Consequences: local configuration, authentication, provenance, integrity, journal, and lock failures exit 2 and do not restart. A timeout or explicitly recognized DNS, connection, rate-limit, or server-availability attestation error exits 75 without observing. systemd waits at least 60 seconds and retries without a finite start-count limit, so repeated transient failures cannot latch the service off and recovery can still be recorded after continuity has failed. Missing attestations, policy/signature rejections, and unrecognized failures remain exit 2. No retry grants authority. Startup still requires live GitHub access. The service blanks paper-write opt-in, loads credentials only from a private repository `.env`, logs to journald, and exits after either final campaign result. Migration preserves database and sidecar bytes, refuses active observers, never recursively changes ownership, and leaves Week 1 archives untouched. A 600-second interval leaves limited reboot tolerance; sufficiently long host, network, DNS, broker, or provenance-verification outages still fail continuity.
- Revisit when: the bounded VPS recovery drill exposes a missing boot dependency or the observation store moves off-host.

## 2026-08-12 — Close M5 with an explicit sustained-duration waiver

- Decision: accept the shorter passing reboot/recovery validation and the healthy portion of the stopped follow-up campaign, and waive the remaining unobserved part of the 168-hour requirement for the current M5 operational closeout.
- Context: Week 1 preserved a failed continuity gate. The later shorter validation passed, and the longer follow-up remained healthy until it was intentionally stopped before 168 hours.
- Consequences: M5 operational work closes without rewriting Week 1 evidence or claiming that the full 168 hours passed. The unobserved duration remains an explicit evidence gap. The waiver grants no paper activation, broker-write, live, research-qualification, or strategy-promotion authority, and the restart-safe supervision controls remain available.
- Revisit when: a later paper-operation decision depends on full-duration sustained evidence or new operational evidence invalidates the shorter validation.

## 2026-08-13 — Campaign V1 binds one complete dataset set before execution

- Decision: record the Alpaca adapter and IEX feed in dataset identity, require the reviewed SPY/QQQ `5m` universe, fully validate all four frozen period datasets, and bind all 60 Campaign V1 reservations in one transaction. Keep the sealed `base_code_commit` as the reviewed M5B foundation reference and block Campaign V1 execution until the actual checkout or build identity is separately reviewed and recorded.
- Context: per-candidate binding allowed a run before the other three period datasets existed, the plan's provider label did not match the concrete manifest adapter name, manifests omitted the selected feed, mutable universe configuration could change later binding, and reports could present the old reviewed commit without proving which reconciled code executed them.
- Consequences: missing, corrupt, substituted, repeated, partial, or changed binding fails before a candidate is claimed and cannot burn one ordinal. The sealed plan, costs, delays, dates, parameters, ordinals, policy fingerprint, authority flags, and foundation reference remain unchanged. If the execution source differs materially from the reviewed source surface, a new campaign version is required.
- Revisit when: a reviewed execution-source provenance contract can identify the running source without rewriting sealed Campaign V1 fields.

## 2026-08-13 — Zero scheduled early closes satisfy complete coverage

- Decision: interpret `early_close_coverage` as complete when a fully validated XNYS period reports any nonnegative integral scheduled-early-close count, including zero.
- Context: Validation A, B, and C contain no scheduled early closes, while the reviewed policy rationale requires complete coverage for any reported early-close sessions. Requiring a positive count would make all nine validation base candidates fail regardless of data completeness.
- Consequences: zero is a vacuous coverage pass only after calendar and dataset validation. Missing, malformed, fractional, or negative counts fail. The policy file, threshold, fingerprint, periods, and candidate identities remain unchanged.
- Revisit when: a later policy version records expected and observed early-close sessions as separate metrics.

## 2026-08-13 — Campaign V1 records execution identity outside the sealed plan

- Decision: keep Campaign V1's `base_code_commit` as its reviewed M5B foundation reference. Separately assess the main-only GitHub-attested wheel, the canonical GitHub CLI path and SHA-256 used for both attestation checks, exact non-editable installed project package, sealed-lockfile dependency wheels and installed files, and a CPython 3.12 standard-library `venv --without-pip` runtime invoked only with the fixed `-I -B -S` bootstrap. Compare every `.py` file in the application package against wheel-bound `intraday_campaign_v1_surface.json` (48 modules): foundation-exact, an exact reviewed delta, or a reviewed new file. Record one immutable explicit review while all 60 candidates remain pending. Bind a fresh matching assessment to each candidate in the same transaction that claims it, and verify the runtime again before publishing its report.
- Context: the sealed foundation reference identifies the code reviewed before preregistration, not the later checkout or build that executes a candidate. Installed dependency metadata can be rewritten with altered files, and a component-only surface can leave result-affecting code outside the review boundary. The inert surface manifest is wheel-bound but cannot verify itself.
- Consequences: added, missing, or byte-mutated application modules fail; there is no AST normalization. The application wheel may contain only the project package and its own distribution metadata, so it cannot add an unmanifested top-level importable file. The attestation verifier is resolved once to an absolute canonical executable named `gh`, checked before and after both exact-path calls, and retained in the assessment; a changed path or bytes fails later equality checks. The verifier file and every install-path ancestor must be owned by another trusted account and non-writable by the execution account, so stable caller-selected substitution also fails. The reviewed deltas include PR #114 dataset-feed identity patch `3a339ab7866a22a2e200aee617395d9cc05e45c9` / diff `4ac13c3d58d675544a11b4bb00ea9d52996e53b1dc6e84c21658fc0485ec7f92` and domain patch `952fc104c15c25260b0e29488df7ab61ae4b9a50` / diff `c3ded022ed3c9a7a8841c09c8d8c32dac167227c4e4bd084b0ef0605b564a65d`. The human reviewer must inspect the full main-attested source commit and wheel, the verifier path and hash, and the assessment fingerprint. A source-surface mismatch requires Campaign V2. Missing review, artifact or installed-byte mismatch, unexpected dependency, unsafe Python path, `.pth`, startup customization, cached bytecode, altered import hooks, or post-computation drift fails closed. The mechanism grants no holdout, paper, broker-write, or live authority.
- Revisit when: a future campaign uses another reviewed surface, the dependency lock changes, or execution moves to a runtime whose interpreter or wheel-install contract needs another version.

## 2026-08-13 — Filter Alpaca intraday transport extras at the adapter boundary

- Decision: for `1m` and `5m` requests, derive the exact expected XNYS regular-session bar-open set in `AlpacaHistoricalProvider`. Map every returned bar, retain every mapped record in immutable raw evidence, and send only requested-symbol records on that exact grid to dataset normalization. Keep unexpected symbols in the validation stream and keep `DatasetService` and `validate_records` strict.
- Context: the first Campaign V1 Training import returned the complete expected grid plus 2,758 premarket, postmarket, normal-close-boundary, and early-close-boundary records. The adapter used the grid only to set Alpaca's exclusive end, so correct dataset validation rejected the whole import before publication.
- Consequences: transport extras cannot enter normalized Parquet. A published dataset binds them into `raw.jsonl`, its fingerprint, and dataset identity; a rejected import binds mapped acquisition records and their fingerprint into quarantine evidence. Missing or duplicate requested intervals, invalid mapped OHLCV even outside the requested grid, unexpected symbols, and malformed payloads or bars still fail. Daily behavior and broker authority do not change.
- Revisit when: a provider supplies a native regular-session filter with evidence strong enough to replace local exact-grid selection, or raw HTTP payload retention receives a separate storage and privacy design.

## 2026-08-13 — Abort Campaign V1 and preregister Campaign V2

- Decision: keep `intraday-research-v1` as immutable evidence of an attempt aborted before dataset publication or candidate execution. Block new V1 sealing, dataset binding, source review, and execution. Preregister `intraday-research-v2` with the unchanged 60-candidate design, plan fingerprint `52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122`, foundation reference `f3d7ee7d86c3a02b52c09270a6399aa1bf5f78b7`, and a new exact 49-module wheel surface that includes the corrected provider.
- Context: V1's source review was recorded, but its source surface cannot describe the corrected execution code. No strategy result was observed, so carrying forward the fixed matrix does not use result-driven information.
- Consequences: V1's sealed plan, stored review, runtime state, candidate records, and quarantine evidence remain readable and immutable. V2 uses the existing campaign-keyed source-review and candidate-binding tables without migration and preserves main-only attestation, trusted-verifier, exact install, fixed-lock, isolated-runtime, per-candidate reassessment, and no-broker-authority controls.
- Revisit when: V2 observes its first candidate result, another software or data defect changes the reviewed execution surface, or a later campaign changes the research design.

## 2026-08-13 — Close Campaign V2 as immutable failed evidence

- Decision: record `intraday-research-v2` as complete at 60/60 controlled candidates, with all 12 base research qualification groups failed and no holdout access or authorization. Preserve its plan, exact-weight execution, source review, reports, qualification evidence, and 49-module source manifest unchanged.
- Context: V2 reported extreme turnover and transaction costs. Adding recorded costs back to net P&L produced results near zero, while longer delays reduced turnover and improved net returns.
- Consequences: V2 remains valid failed evidence under its frozen semantics. Source inspection confirms that repeated 0.5 targets recalculated exact quantities after drift and that pending orders made longer delays suppress later target applications. The delay variants therefore confound latency and application cadence. These findings do not prove a profitable zero-cost signal or permit weaker gates, parameter tuning on V2 dates, holdout access, or execution authority.
- Revisit when: an integrity review contradicts the supplied campaign closeout or diagnostic export identity. A new result does not rewrite V2; it creates separate evidence.

## 2026-08-13 — V3 queues state changes instead of repeated exact weights

- Decision: add `state-transition-delayed-fifo-v1` under `intraday-experiment-v2`, `intraday-backtest-report-v2`, and `XNYS-regular-session-state-transition-flat-v2`. Evaluate SPY/QQQ desired state every completed five-minute slice, queue each changed per-symbol state for the Nth later same-session open, preserve FIFO order without supersession, and create no order for an unchanged state. Support no periodic rebalance.
- Context: V2 rescheduled unchanged targets and recalculated their quantity from current equity. Its one-pending-order rule changed accepted target cadence as delay increased.
- Consequences: an entry sizes once, an exit closes the held quantity, and price drift alone cannot trade. Later decisions remain queued while earlier transitions wait. At the deterministic close cutoff, the session controller records and cancels queued work, records late changes as rejected, and schedules any required final-open exit. Complete XNYS sessions, completed-bar causality, normal and early-close safety, and flat overnight state remain mandatory. V1/V2 code, IDs, golden fingerprints, and manifests remain unchanged.
- Revisit when: measured research needs periodic rebalance, supersession, partial fills, quote latency, auction execution, or another stale-state rule. Each requires a new reviewed contract.

## 2026-08-13 — V3 diagnostics and campaign design remain non-authoritative drafts

- Decision: pair each V3 realistic replay with `zero-cost-counterfactual-v1` on the identical semantic trace, and fingerprint both in `intraday-backtest-report-v2`. Fix three future strategies: the V2 12-bar MA signal, six-bar momentum, and a first-six-bar opening-range breakout that enters only after a later completed close exceeds the range high and then holds until close. Draft 60 candidates from three strategies, four roles, and five fixed cost/delay variants; keep cash outside the budget.
- Context: a cost add-back cannot reconstruct sizing, and V2 dates are exposed. An exact paired replay separates signal-path diagnostics from realistic cost results without turning the diagnostic into qualification evidence.
- Consequences: zero-cost results cannot enter qualification or grant authority. `intraday-qualification-policy-v1` thresholds remain unchanged, but a reviewed V3 report binding is still required. Training and Validation A/B/C dates stay unset. The selector rejects known exposed validation overlap and never certifies freshness; independent review must first inventory every observed window. All V2 dates from 2025-07-01 through 2026-06-30 are exposed. The V3 draft cannot seal or execute, and a future whole-package source manifest must include `intraday_v3.py`.
- Revisit when: the exposure inventory, exact forward validation periods, qualification binding, source review, runtime closure, and independent datasets are ready for preregistration.

## 2026-08-13 — Unresolved external freshness blocks V3 sealing

- Decision: retain a fingerprinted repository-known exposure inventory and calendar-only candidate period selection, but leave every V3 validation approval false until a separate attestation covers ignored runtime state, provider records, other clones, and human exposure. Add the non-authoritative V3 realistic-cost qualification binding, whole-package manifest build step, and artifact preassessment, but do not create a final plan, registry reservations, dataset binding, source review, runner, or execution command.
- Context: the audit found dated daily, V1, V2, strategic-allocation, and paper-account exposure through 2026-08-11. Validation A/B/C avoid all dated disqualifying entries, but repository evidence cannot prove universal freshness. The task requires unapproved periods rather than fabricated certainty when freshness remains unresolved.
- Consequences: inventory fingerprint `0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9` and selection fingerprint `d371488a56a1b960ebb54c9d5a1cfe46e043523e21c99a49da392e69cc75d0b1` describe candidate periods only. Training may reuse 2025-07-01 through 2026-06-30 as explicitly exposed evidence. Validation A is 2026-08-14 through 2026-10-16, Validation B is 2026-10-19 through 2026-12-18, and Validation C is 2026-12-21 through 2027-02-26. Binding fingerprint `11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3` keeps every v1 threshold, consumes only `realistic.metrics`, verifies each completed registry report and its reviewed source evidence, requires durable reasons for failed records, and grants no authority. The build workflow can attest a canonical exact-byte manifest for every package source file only after merge. The preassessment can then verify the same trusted `gh` identity across the attested wheel, build manifest, and whole-package manifest plus the installed package, fixed lock, exact dependency wheels, and isolated runtime. It remains artifact evidence only and cannot create a campaign, source review, binding, dataset, runner, or authority. No V3 contract or candidate can run or qualify. Caller-configured V1 research remains separate and cannot become V3 evidence; any use on candidate dates creates exposure. The future sealed V3 contract must reserve its namespace and expose only a V3 stored-spec runner. No V3 plan fingerprint exists, no market data or result was observed, and V1/V2 evidence remains unchanged.
- Revisit when: an independent freshness attestation approves or rejects each candidate validation period. Approval permits a separately reviewed versioned preregistration; rejection requires new periods and a new selection fingerprint.

## 2026-08-13 — Prospective market-data freshness permits conditional V3 preregistration

- Decision: distinguish unprovable universal freshness from prospective market-data freshness. Mark three future validation blocks eligible under `main-attested-design-before-first-market-bar-v1`, but keep prospective freshness and validation approval false until the exact exposure inventory, period selection, final plan, and qualification binding receive a verified GitHub/main seal attestation. The author-recorded selection date is descriptive. The verified Sigstore transparency-log timestamp for the exact seal digest is the only effective selection cutoff, and it must precede Validation A's first bar. Local clocks, Git timestamps, filesystem times, and caller-entered verification times cannot prove the cutoff.
- Context: unknown local or external historical state can contain unrecorded past observations, so universal freshness remains false. It cannot contain actual SPY/QQQ bars or strategy results from a market period that has not begun. The original August 14 start left too little review and attestation time, so the replacement periods were chosen from XNYS calendar metadata without market values: Validation A 2026-10-01 through 2026-12-03, Validation B 2026-12-04 through 2027-02-09, and Validation C 2027-02-10 through 2027-04-15, each with 45 sessions.
- Consequences: the unchanged inventory fingerprint is `0666996faabb50abce0b8959c49980e36a655ea290618bc1463342d2ab5122f9`; selection fingerprint is `c2718c3871bb95e22d4647e119f6bfb54cd51ec7b1b2cc472cfa1a7dfbcfc5d0`; final plan fingerprint is `5e81cf8f0db1143f293a0f93900f1e797718443a559c1caaaa2e986851d5241a`; qualification binding remains `11ce501cafc2ad0078d5750e185470dccbbf17a8b01b4ecfd95159c615b45cc3`. The earlier V1 period selection remains historical evidence. Seal creation and verification run the exact inventory, selection, plan, and qualification binding through their shared strict parsers; recomputing fingerprints after adding a known overlapping acquisition cannot make the design sealable. The final plan fixes three strategies, four periods, five variants, 60 strategy-major reservations, no parameter neighbors, and false authorities. The static file creates no runtime state. The V3 registry itself verifies the seal and stores its exact bytes with the trusted-time evidence before it may create reservations. It resolves four dataset IDs through the shared catalog, fully validates each dataset, and writes no dataset or spec row unless the complete four-role bind passes. Source review reruns the artifact assessment and requires its explicitly reviewed fingerprint. Each claim has a random lease token required for every later lifecycle mutation. Report publication commits an immutable canonical-report intent before the create-only final file, syncs the report directory before completion, transfers stale intent ownership atomically, and reconciles completed intents from the durable journal. A running path conflict records terminal failure; substituted bytes after completion create immutable integrity-conflict evidence that blocks qualification without rewriting the completed result. Registered qualification reads roles from the immutable stored plan, uses only `realistic.metrics`, and fingerprints every one of the 60 terminal sources. V1/V2 files, contracts, fingerprints, and evidence remain unchanged.
- Revisit when: main attestation misses `2026-10-01T13:30:00Z`, any selected-period data or result informs the design before that seal, a bound manifest or source review fails, or the final plan changes. Any such event requires rejection or a new versioned selection and plan. Candidate 1 cannot run before Validation C's final bar completes at `2027-04-15T20:00:00Z`, and then only after all four datasets bind and the source review exists. No research qualification, protected holdout, paper, broker-write, or live authority is granted.

## 2026-08-14 — Rapid Research stays separate from promotion authority

- Decision: make ordinary historical iteration cheap through a separate Rapid Research CLI, store, data-import path, strategy registry, backtest, bounded sweep, chronological walk-forward evaluator, execution stress, and zero-authority candidate export. Reuse only broker-free domain, simulation, fingerprint, calendar, catalog-read, and Parquet primitives.
- Context: controlled experiments, preregistration, protected holdout, build provenance, and operator approval are necessary near promotion, but they made early strategy discovery too slow and V3 too central to daily development.
- Consequences: Rapid state lives only in `rapid-research.sqlite3` and `rapid-research/`. Every export sets controlled evidence, qualification, protected holdout, paper, broker-write, live, and automatic-promotion authority false. Rapid code does not import protected authority modules. Before catalog or local reads, it reads but never writes the active controlled registry and rejects both the post-validation tail reserved by an unused holdout authorization and every stored holdout experiment range. Direct imports from identifiable controlled catalog artifact directories are rejected even when another `TRADING_LAB_HOME` is active. A detached or re-encoded user file has no intrinsic catalog provenance; policy forbids copying protected bars into Rapid. Local data remains user-supplied with unknown adjustment policy. Inclusive overlap with V3 Validation A/B/C is rejected without an override. V1/V2 manifests and V3 plan, periods, strategies, qualification binding, execution semantics, and runtime state remain unchanged.
- Revisit when: measured research volume requires resumable execution, another parameter type, or a reviewed promotion importer. Any importer must remain a separate human-reviewed controlled boundary and cannot turn old Rapid artifacts into authority by mutation.

## 2026-08-14 — Paper continuation carries settled lineage without broker authority

- Decision: split a later strategic-allocation paper session into a maximum-24-hour continuation declaration, an atomic evidence-completion handoff, and a broker-free deterministic planner. Give each authorization at most one successor, start it no earlier than the prior authorization's expiry, and require a completed handoff when its source is another continuation. Copy the prior authorization's candidate, strategy, parameters, code, dataset, universe, qualification, account, and risk configuration into a new immutable authorization. Do not give that declaration a flat baseline or usable risk context. Complete it only from fresh production-attested portfolio and market evidence with exact settled positions, no nonterminal order or active reservation, and clear emergency state. Append the current non-flat reconciliation, settlement, strategy-equity checkpoint, and handoff in one transaction. Generate replay and shadow targets from that immutable handoff through the existing action-plan schema. Trace planning through the declaration chain to the root authorization's first fill-backed checkpoint, derive root and current sessions from their attested NYSE core clocks, count inclusive XNYS sessions, and derive the market-state fingerprint from canonical current evidence. Accept neither the session count nor market-state fingerprint from the caller.
- Context: the 2026-08-04 session left valid strategy positions and adverse-history lineage. Reusing the initial flat bootstrap would erase positions, fills, peak equity, or drawdown. Supplying replay and shadow files by hand would not prove that the current account state produced them. Caller-supplied timing or market identity could also force or suppress a scheduled rebalance without changing the stored evidence.
- Consequences: historical authorizations and baselines remain unchanged. A continuation checkpoint carries fill IDs, gross buy and sell notional, fill-cost reserve, strategy cash, positions, equity peak, and drawdown, then marks the carried positions at current bids. Later fills continue from those cumulative economics. A new or chained continuation cannot reset the root strategy epoch. The planner emits whole-share long-only targets and deltas for only `strategic-allocation-21`; a non-rebalance session emits current quantities as a no-op. Its intent fingerprints remain the authorization-bound dataset and parameter fingerprints, while root session, current session, present state, handoff, risk, clock, quote, market-state, and source-state evidence remain explicit plan evidence. Declaration, completion, and planning grant no intent, risk, activation, broker-write, live, or promotion authority.
- Revisit when: another qualified strategy needs continuation or the approved sizing, rebalance, or exchange-session contract changes. Any change requires a new reviewed version rather than weakening this handoff.

## 2026-08-14 — Planning refreshes present state without rewriting the handoff

- Decision: keep the completed continuation handoff and its checkpoint as immutable historical lineage. Before deterministic continuation planning, collect a new production-attested portfolio snapshot, complete IEX quote set, and NYSE clock through Alpaca GET requests only. Append a planning-state settlement bound to the handoff and a strategy-equity checkpoint bound to the prior checkpoint and fresh risk input. Require an explicit planning checkpoint when deriving a plan, and bind the handoff plus fresh settlement, mark, snapshot, quotes, and clock into market-state and source-state identity.
- Context: production continuation authorization `paper-sa-continuation-20260814T133456Z` completed a clean non-flat handoff, but `paper plan` reused the exact risk input frozen into that handoff. The 15-second risk limit then made a valid handoff unusable after ordinary handoff processing. Extending the limit or replacing the handoff would weaken freshness or historical lineage.
- Consequences: handoff age no longer determines current planning freshness. The 15-second limit still applies to the new account/position/order observations, every quote, the NYSE clock, and the planning mark. Fresh state must retain the approved account, authorization, strategy, risk configuration, cash, settled positions, clear emergency generation, no broker open order, and no unresolved mutation or incompatible reservation. Account equity and buying power remain fresh broker facts and may move with market prices. The planning checkpoint carries fills, cost reserve, and strategy cash; its peak is `max(inherited_peak, current_equity)`, so refresh cannot create a flat baseline or reset drawdown. `paper plan` can issue GET requests and append local evidence, but it cannot construct a submit/cancel transport or grant intent, risk, activation, broker-write, live, or promotion authority. The failed production authorization remains immutable historical evidence.
- Revisit when: planning needs a reviewed expected advance beyond unchanged settled positions, another strategy needs this continuation contract, or broker account semantics require a separately reviewed stable-state comparison.

## 2026-08-14 — Rapid-002 qualification binds two exact combined stresses

- Decision: extend the daily qualification manifest only for the Rapid-002 Stress A and Stress B roles. Each record must share its named base record's source, strategy, data, universe, parameters, period, and seed while changing both cost and execution model to the exact declared versions. Expose each stress return and same-base retention separately; use strict positive-return and at-least-80%-retention gates for both stresses.
- Context: the existing manifest accepted isolated cost or delay variants but rejected a record that changed both. Its gate contract compares one metric per gate, while the promotion design states two compound requirements.
- Consequences: the candidate-specific manifest freezes 28 experiment IDs at fingerprint `b997afb53fdf05ef26be72934fb3318cb582ba503f4527fa9ca96f88f7b72693`. Four machine gates represent the two compound requirements. The existing 17 approved gates and historical manifest fingerprints remain unchanged. This change creates no experiment, qualification, independent-evaluation access, holdout authority, paper authority, broker state, or V3 state.
- Revisit when: another reviewed candidate needs a combined stress with different roles or semantics. Do not generalize from this campaign without that concrete requirement.

## 2026-08-14 — Rapid-002 execution uses one sealed stored-input plan

- Decision: add `controlled-validation-campaign-plan-v1` only for Rapid-002. After this change merges, require a clean checkout whose `HEAD`, local `main`, and `origin/main` are equal; verify the preserved Rapid source diff, strategy hash, candidate export, dataset integrity, evidence manifest, and proposal; then atomically store the exact 28 validation reservations. Run each reservation by experiment ID only. Derive cash, strategy, parameters, range, data, costs, and delay from the stored plan.
- Context: `training-campaign-plan-v1` is training-only and fixes 5/1 basis-point costs with a one-bar delay. The generic daily runner accepted caller-supplied inputs. PR #126 bound qualification roles but did not create an executable 28-record plan.
- Consequences: the Rapid-002 campaign namespace is reserved. Its campaign, plan, and reservation identities are immutable, completed or failed records cannot rerun, and qualification requires the exact stored plan fingerprint and all 28 plan-bound records. The plan fingerprint cannot exist until the final execution change is merged because the plan binds that merged commit. This change creates no campaign, experiment, qualification, independent evaluation, holdout, paper, broker, live, or V3 state.
- Revisit when: another daily candidate needs non-default sealed execution inputs. Add a reviewed schema version; do not widen Rapid-002 or alter historical `ExperimentSpec` fingerprints.

## 2026-08-15 — Daily acquisition can name a versioned universe

- Decision: let `data import-alpaca` accept one explicit daily universe file and require its complete membership set. Enforce a declared acquisition range before provider construction and bind extended universe files by their full content. Keep the five-ETF universe as the default.
- Context: Rapid-004 needs a predeclared expanded seed pool without changing the dataset and strategy lineage used by prior campaigns or `strategic-allocation-21`.
- Consequences: the existing universe and datasets remain unchanged. A custom import still requires research mode, read-only Alpaca access, complete membership coverage, adjusted bars, full validation, and immutable dataset publication. It cannot silently drop later-inception members or leave a declared acquisition range. Intraday imports reject the option.
- Revisit when: a reviewed universe format supports multiple membership intervals or another venue requires a different symbol-selection rule.

## 2026-08-15 — Rapid-004 uses a labeled Yahoo fallback when Alpaca rejects access

- Decision: add one daily-only Yahoo chart adapter for versioned USD ETF universes. Map vendor timestamps through `America/New_York`, scale all OHLC values by adjusted close divided by close, retain vendor volume, and label the result `yahoo-adjusted-ohlc-v1` with no claimed feed.
- Context: the existing external Alpaca credential pair returned HTTP 401 on the exact Rapid-004 range before any dataset was published. Changing broker credentials is outside this program. The unauthenticated Yahoo endpoint was reachable, and its metadata and adjusted-close arrays can enter the existing immutable dataset validator without a new data store.
- Consequences: Alpaca remains the default and every existing dataset and protected adjustment check stays unchanged. Yahoo imports require research mode and an explicit versioned daily universe, enforce its acquisition and membership ranges before network access, retain mapped source-bar evidence, and grant no qualification, paper, broker-write, or live authority. `config/research/rapid-004-acquisition-fallback-v1.json` records the operator decision before liquidity or strategy results; it is not a runtime control or part of the dataset identity. The final universe freeze binds the provider, policy, dataset, and fingerprints.
- Revisit when: valid Alpaca research credentials return, Yahoo changes its chart contract, or a controlled candidate needs an independently reviewed provider policy.

## 2026-08-15 — Rapid-004 freezes a 37-ETF no-return universe

- Decision: screen the immutable 40-symbol seed snapshot over 2020-07-27 through 2022-12-30 with exact Decimal median of normalized adjusted close multiplied by Yahoo vendor-reported integer volume. Retain IWD over IVE, IWF over IVW, and EEM over VWO because each winner has higher median daily dollar volume. Freeze the other 37 symbols with their categories and sleeves, then acquire and bind a separate immutable 2020-07-27 through 2026-07-31 snapshot under that final universe identity.
- Context: all 40 seeds had 614 complete selection sessions and exceeded the fixed `$10M` threshold. The seed file described adjusted daily volume, but the Yahoo fallback recorded before screening retains vendor volume unchanged and supplies no adjusted-volume field. Every duplicate pair differed on the first predeclared tie-breaker, so no subjective fallback criterion was used. Yahoo returned different adjusted OHLC values between the seed and final retrievals.
- Consequences: `config/research/rapid-004-final-universe-v1.json` records all 40 exact dispositions and the selection snapshot. `config/research/rapid-004-universe-freeze-v1.json` binds final universe fingerprint `d57039d3a172337c78ad8206644feeb72d76d124ce33a4e5cbe4733dbb2e94e3` to 55,907-bar dataset `450e329a8f11f1bd19dcc37ac417b2c59a262e875723eb668332beb22c48d3ff`, fingerprint `ac506268e019a03f7e9e202858171141c3f2d63fc88e03649a1dda091ac47304`. Rapid-004 commands must pass `--campaign rapid-004-expanded-universe`; the resulting run specification binds the freeze, fully verifies the dataset artifacts, and rejects a different dataset, universe, symbols, range, provider, or adjustment policy before strategy execution. Unbound Rapid runs cannot count toward the program. Selection remains bound to the seed snapshot; strategy research must use the final snapshot. No return, strategy result, protected range, V3, broker, paper, live, or `strategic-allocation-21` state informed the choice.
- Revisit when: a later program declares a new universe before inspecting its results. Do not mutate this freeze or substitute another Rapid-004 dataset.

## 2026-08-15 — Rapid-004 predeclares its complete exposed research design

- Decision: freeze one immutable Rapid-004 artifact before strategy execution. It fixes the exact role partitions, a 40% SPY / 20% EFA / 30% AGG / 10% GLD 21-session gate benchmark, all A-U hypotheses and grids, three fixed blocks, 252/126/126 rolling walk-forward design, normal and four worse-execution variants, direct-neighbor topology, one uniform screen, cohort selection, and controlled-plan bounds. The worst-case parent-record budget is 2,452, below the fixed 3,000 ceiling.
- Context: the expanded universe adds enough strategy, subset, benchmark, and portfolio choices that declaring only the universe would still permit result-adaptive family mechanics, grids, gates, and benchmark selection.
- Consequences: the artifact also fixes every strategy ID's mechanic, role group, fallback, weighting, and cap. Generic campaign commands verify the artifact and then fail closed before reading bars; a planned runner must enforce the exact family, stage, profile, parameters, period, execution scenario, neighbor relation, and cumulative budget before it can create a campaign row. Every later campaign-bound run must record the exact predeclaration, role-map, benchmark-suite, research-plan, and exposed-screen SHA-256 values. The unchanged approved daily gates remain disqualifying. Prospective additions require nine complete walk-forward folds, positive compounded out-of-sample return, at least two-thirds profitable folds, no fold below -10%, and at most 50% positive profit from one frozen sleeve. The sleeve and walk-forward rules received independent read-only control review before any Rapid-004 result. Missing metrics fail. Zero final cohort remains valid, and each nonempty controlled candidate plan stays at or below 38 records. No Rapid-004 strategy result informed this decision.
- Revisit when: Rapid-004 closes. Do not mutate this artifact after a result; a later program needs a new versioned predeclaration.

## 2026-08-15 — Rapid-004 uses one dedicated frozen-plan runner

- Decision: keep Rapid-004 outside the ordinary strategy registry and caller-configured Rapid commands. Expose only fixed `plan`, `status`, and `run` actions. The runner derives every benchmark, strategy profile, grid point, period, scenario, stage transition, neighbor, screen, and cohort choice from the reviewed predeclaration. It validates the complete frozen catalog, normalized artifact, and raw artifact before creating a campaign run row.
- Context: ordinary Rapid accepts caller-supplied datasets, strategies, parameters, dates, costs, and delays. Its fixed-five strategy implementations, metrics, and Rapid-002 controlled plan cannot represent the 37-symbol atomic targets, sleeve profit attribution, fixed diversified benchmark, A-U stage rules, or Rapid-004 budget without weakening the campaign binding.
- Consequences: campaign decisions always expand to all 37 symbols, stay long-only with cash residual, and record the frozen binding in create-only reports. Parent rows and linked walk-forward, sensitivity, and stress children have distinct budget treatment. The runner executes every global stage in frozen order, derives direct neighbors only from each family's declared axes, and queues state changes through the declared fill delay. Resume validation rebuilds every allowed specification and checks its SQLite projection and canonical report bytes before use. The simultaneous cohort artifact groups by the declared diversity field and embeds each nonempty candidate's exact neighbors and at-most-38-record controlled plan; an empty cohort has no controlled plan. The historical strategic-allocation benchmark calls the unchanged strategy through a zero-expanding universe adapter. A clean reviewed source commit is required. Generic `--campaign rapid-004-expanded-universe` remains fail-closed, and no controlled, holdout, V3, paper, broker, live, or promotion authority is added.
- Revisit when: a frozen nonempty cohort needs its separately reviewed controlled runner. Do not widen the exposed runner or reuse the Rapid-002 plan.

# Operations

1. Set `TRADING_LAB_HOME` to an isolated writable directory when the default is unsuitable.
2. Run `trading-lab doctor`; stop on any failed check.
3. Import offline fixtures with `trading-lab data import-fixture`.
4. Inspect `trading-lab status`, `data describe`, and `data validate`.
5. Preserve the dataset directory and manifest together when moving evidence.

Recovery: artifact directories are authoritative. After moving a disposable `catalog.sqlite3` aside,
run `trading-lab data rebuild-catalog`. Never edit an artifact in place. The execution store can list
journal-verified `submission-unknown` orders without changing state. The production reader can retain
a sanitized immutable 404 from an exact lookup, but that result is historical evidence only. A
read-only proof can bind it to later complete clean reconciliation and the unchanged protected
controls for operator review. It does not authorize retry. Guarded paper submit and single-order
cancel paths exist; no blind retry or live recovery path exists.

Run this command to inspect paper blockers without changing the execution database:

```console
trading-lab paper assess-startup --authorization AUTHORIZATION_ID --risk-config config/risk/alpaca-paper-v1.json
```

Supply both `--wheel` and `--manifest` only from an installed attested build. A nonzero result means
paper startup is blocked; never bypass a listed reason.

Cancellation recovery also remains read-only. Run a production exact-client-order lookup after the
attempt and any unknown outcome, then assess its immutable lookup provenance. Only a latest matching
terminal event can report `resolved-canceled`, `resolved-rejected`, or `resolved-filled`. A
nonterminal or stale lookup remains unresolved. No result authorizes another broker call.

Before any future paper mutation work, use [paper-write-readiness.md](paper-write-readiness.md). Its
current status is not ready for another broker call, and every listed blocker remains mandatory.
Process opt-in opens only
the outer runtime gate and cannot override transaction-bound authority.

## Sustained paper observation

Start a bounded read-only campaign with `trading-lab paper start-observation CAMPAIGN_ID`. Set its
maximum gap to the planned sampling interval plus measured scheduler tolerance and set an explicit
duration. Run `record-observation` on that schedule and `assess-observation` after interruptions.
`healthy_now` describes only the latest sample and staleness. `continuity_held` compares the largest
completed sample gap with the immutable configured maximum. `campaign_passed` remains null until the
campaign ends, then requires current health, continuity, and no historical drift. A recovered read
failure remains in `failure_count` but does not alone fail the campaign. `campaign_reasons` records
final blockers. A completed failed campaign exits nonzero even when `healthy_now` is true. Campaign
completion remains stale unless a final sample falls within the configured gap of the end time.
Failure records contain no broker response text. These records grant no activation, risk,
settlement, emergency, or broker authority.

### Week 1 closeout

Campaign `paper-week-1-vps-20260804` completed with 1008 healthy samples, no position drift, and one
isolated read failure that recovered at the next 10-minute sample. Its final state was healthy. The
largest observed gap was approximately 1030.755 seconds, reported as 1031 seconds. It exceeded the
fixed 900-second limit, so continuity and the final campaign result failed. VPS logs show two orderly
whole-host reboots during that gap. The cause
distinguishes the event from an unexplained application stall but does not turn the failed limit into
a pass. The preserved database remains the evidence source; do not edit or replace its observations.

Record action-plan equivalence with `paper record-equivalence`. Supply one replay plan, one shadow
plan, and every paper intent key for the decision. Replay and shadow files use this strict shape:

```json
{
  "schema_version": "paper-action-plan-v1",
  "strategy_id": "strategic-allocation-portfolio",
  "strategy_version": "1",
  "source_data_fingerprint": "64 lowercase hexadecimal characters",
  "configuration_fingerprint": "64 lowercase hexadecimal characters",
  "targets": [{"symbol": "SPY", "quantity": 4}],
  "evidence_fingerprints": ["64 lowercase hexadecimal characters"]
}
```

The store derives the paper plan from the named immutable quantity intents. It compares strategy,
source data, configuration, and sorted targets. A mismatch remains evidence and exits nonzero. The
comparison reads no broker state and grants no execution authority.

## Continuation paper session

The 2026-08-04 initial session established the flat strategy baseline and filled GLD 3, IWM 8, QQQ
3, and SPY 4. Do not create another flat baseline. A later session uses two append-only steps.

1. Confirm the prior authorization has no existing successor, has expired, and has a latest settled
   strategy-equity checkpoint, no nonterminal order, no active reservation, and clear emergency
   state. A continuation source must also have a completed handoff. Use valid dedicated Alpaca PAPER
   credentials; the current sanitized HTTP 401 response is a credential blocker, not a reason to
   change authentication code.
2. From the verified unprivileged runtime, declare a new authorization no longer than 24 hours:

   ```console
   trading-lab paper authorize-continuation NEW_AUTHORIZATION \
     --previous-authorization PRIOR_AUTHORIZATION \
     --risk-config config/risk/alpaca-paper-v1.json \
     --authorized-by REVIEWER \
     --reason "REASON" \
     --authorized-at AUTHORIZED_AT_UTC \
     --expires-at EXPIRES_AT_UTC
   ```

   This stores the new authorization and continuation declaration in one transaction. It creates no
   baseline, risk context, intent, activation, or broker-write authority.
3. Complete the declaration from fresh GET-only Alpaca account, position, open-order, quote, and
   clock evidence:

   ```console
   trading-lab paper complete-continuation NEW_AUTHORIZATION \
     --risk-config config/risk/alpaca-paper-v1.json \
     --operator OPERATOR \
     --reason "fresh reconciled continuation state"
   ```

   The command rejects stale or mismatched evidence, changed account or risk configuration, dirty
   state, active reservations, nonterminal orders, and emergency disable. One transaction appends
   the non-flat expected snapshot, clean reconciliation, strategy-equity baseline, continuation
   settlement and checkpoint, and final handoff. Prior fills, strategy cash, positions, equity peak,
   and drawdown remain in the new lineage.
4. Collect new planning evidence and generate create-only replay and shadow files:

   ```console
   trading-lab paper plan \
     --authorization NEW_AUTHORIZATION \
     --risk-config config/risk/alpaca-paper-v1.json \
     --replay-plan replay-plan.json \
     --shadow-plan shadow-plan.json
   ```

   `paper plan` performs only Alpaca GET requests for account, positions, open orders, current IEX
   quotes, and the NYSE clock. It appends a new attested portfolio snapshot, risk-input bundle,
   planning-state settlement, and bid-marked strategy-equity checkpoint. The immutable handoff is the
   lineage anchor; its snapshot and risk input are never refreshed or replaced. The planning-state
   comparison requires the same account, authorization, strategy, risk configuration, cash, and
   settled positions, plus account readiness, no broker open order, no unresolved local mutation or
   incompatible reservation, and the handoff's clear emergency generation. Account equity and buying
   power may move with market prices and are retained as fresh account evidence rather than copied
   into the handoff.

   The same 15-second policy applies to the new snapshot, quotes, clock, and planning mark. The age of
   the historical handoff evidence does not block planning. The new checkpoint carries prior fills,
   cost reserve, and strategy cash, marks positions at fresh bids, and uses the greater of inherited
   peak equity and current strategy equity. It cannot create a flat baseline or reset drawdown.

   The planner traces the continuation declarations to the root authorization's first fill-backed
   checkpoint. It derives the root and current sessions from attested NYSE core clocks, counts the
   inclusive XNYS sessions, and binds the handoff plus fresh planning evidence into the canonical
   market-state and source-state fingerprints. Missing, stale, malformed, mismatched, or non-session
   evidence stops planning. Output separates the handoff snapshot from the planning snapshot,
   risk-input evidence, planning checkpoint, root/current sessions, session count, rebalance state,
   targets, and deltas. The operator supplies none of those decision values.

   The command makes no POST or DELETE request and grants no intent, risk, activation, or broker
   authority. On a non-rebalance session it emits current quantities as a valid no-op plan. For each
   quantity intent, copy the emitted `source_data_fingerprint` and `configuration_fingerprint`;
   `source_state_fingerprint` identifies both immutable and fresh planning evidence but does not
   replace the authorization-bound intent fingerprints.
5. Record all quantity intents through the existing guarded path, then run
   `paper record-equivalence` and `paper assess-startup`. Stop for explicit user approval before any
   activation or paper mutation.

The first sustained campaign uses the Windows task `SystematicTradingLab-PaperObservation` as an
external 10-minute timer. It pins the exact attested runtime and campaign ID, runs from the repository
directory so the ignored `.env` loads, starts missed work when the computer becomes available, wakes
from sleep, and expires at the campaign end. It cannot run while the computer is powered off; any
resulting gap remains evidence. The one-shot command and database remain authoritative, not the task.

### Linux VPS configuration

The Week 1 archive remains immutable and out of scope. Upgrade only the VPS working store. The
migration changes ownership metadata in place; it does not copy, replace, or edit SQLite contents.
It hashes the database and every present `-wal`, `-shm`, or `-journal` sidecar before and after the
change. It creates or reuses both observation lock files, holds both locks, refuses active root or
service-user Screen sessions and the systemd unit, and checks `/proc` for another process with the
database or a sidecar open.

Only these paths can become `trading-lab:trading-lab` mode `0600`:

- `/opt/systematic-trading-lab/.env`;
- `.trading-lab/execution.sqlite3` and present `execution.sqlite3-wal`,
  `execution.sqlite3-shm`, or `execution.sqlite3-journal` files;
- `.trading-lab/paper-observation-screen.lock` and `.trading-lab/paper-observation.lock`.

The `.trading-lab` directory becomes `root:trading-lab` mode `1770`. Its sticky bit lets the service
create SQLite journals and locks without letting it replace the root-owned `runtime-builds` entry.
The repository, `.git`, risk configuration, `runtime-builds`, build directory, wheel, manifest, and
verified environment remain root-owned and non-writable by the service user. The migration refuses
unsafe links, multiple hard links, a writable repository root, or any protected runtime path that is
not root-owned and non-group/world-writable. It never uses recursive `chown`.

Use one dedicated, unprivileged service account. Authority-grade runtime verification must run as
that account. Root may own the protected repository and build artifacts but is not an accepted
verifier. The repository and exact attested runtime must
already exist under `/opt/systematic-trading-lab`. Put the wheel and manifest beside the verified
virtual environment:

```text
/opt/systematic-trading-lab/.trading-lab/runtime-builds/FULL_COMMIT/
├── runtime-build-manifest.json
├── systematic_trading_lab-0.1.0-py3-none-any.whl
└── verified-venv/bin/trading-lab
```

Set the fixed paths. Replace only `FULL_COMMIT` and `CAMPAIGN_ID`; use a new short test campaign for
the optional recovery drill below.

```console
REPOSITORY=/opt/systematic-trading-lab
TRADING_HOME=/opt/systematic-trading-lab/.trading-lab
BUILD_COMMIT=FULL_COMMIT
BUILD_DIRECTORY=$REPOSITORY/.trading-lab/runtime-builds/$BUILD_COMMIT
RUNTIME=$BUILD_DIRECTORY/verified-venv/bin/trading-lab
WHEEL=$BUILD_DIRECTORY/systematic_trading_lab-0.1.0-py3-none-any.whl
MANIFEST=$BUILD_DIRECTORY/runtime-build-manifest.json
CAMPAIGN_ID=CAMPAIGN_ID
SERVICE_USER=trading-lab
SERVICE_GROUP=trading-lab
SERVICE_HOME=/var/lib/systematic-trading-lab
GH_CONFIG_DIR=$SERVICE_HOME/.config/gh
GH_CACHE_DIR=$SERVICE_HOME/.cache/gh
```

From the first SSH login, stop the old root runner, prepare the fixed service home, and migrate the
working store before installation. `migrate-state` is safe to repeat after a completed migration. If
the pre-migration `check-state` reports root-owned files, that is the expected upgrade blocker. Any
active process, lock, unsafe path, or protected-runtime error must be resolved rather than bypassed.

```console
ssh VPS_USER@VPS_HOST
cd /opt/systematic-trading-lab
REPOSITORY=/opt/systematic-trading-lab
TRADING_HOME=$REPOSITORY/.trading-lab
BUILD_COMMIT=FULL_COMMIT
BUILD_DIRECTORY=$TRADING_HOME/runtime-builds/$BUILD_COMMIT
RUNTIME=$BUILD_DIRECTORY/verified-venv/bin/trading-lab
WHEEL=$BUILD_DIRECTORY/systematic_trading_lab-0.1.0-py3-none-any.whl
MANIFEST=$BUILD_DIRECTORY/runtime-build-manifest.json
CAMPAIGN_ID=CAMPAIGN_ID
SERVICE_USER=trading-lab
SERVICE_GROUP=trading-lab
SERVICE_HOME=/var/lib/systematic-trading-lab
GH_CONFIG_DIR=$SERVICE_HOME/.config/gh
GH_CACHE_DIR=$SERVICE_HOME/.cache/gh

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --user-group --create-home --home-dir "$SERVICE_HOME" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 \
  "$SERVICE_HOME" "$SERVICE_HOME/.config" "$GH_CONFIG_DIR" \
  "$SERVICE_HOME/.cache" "$GH_CACHE_DIR"
sudo chown root:root "$REPOSITORY"
sudo chmod 0755 "$REPOSITORY"

sudo "$REPOSITORY/scripts/paper_observation_systemd.sh" uninstall
if command -v screen >/dev/null; then
  sudo "$REPOSITORY/scripts/paper_observation_screen.sh" stop
  sudo -u "$SERVICE_USER" env HOME="$SERVICE_HOME" \
    "$REPOSITORY/scripts/paper_observation_screen.sh" stop
fi
! sudo systemctl is-active --quiet systematic-trading-lab-paper-observation.service
! sudo pgrep -af '[t]rading-lab paper (start-observation|record-observation|supervise-observation)'

if sudo test ! -e "$REPOSITORY/.env"; then
  sudo install -o root -g root -m 0600 /dev/null "$REPOSITORY/.env"
fi
sudoedit "$REPOSITORY/.env"
# Expected to report the old root-owned mutable files before the first migration.
sudo "$REPOSITORY/scripts/paper_observation_systemd.sh" check-state \
  "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP"
sudo "$REPOSITORY/scripts/paper_observation_systemd.sh" migrate-state \
  "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP"
sudo "$REPOSITORY/scripts/paper_observation_systemd.sh" check-state \
  "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP"
```

Verify exact owners, modes, store access, and effective runtime protection. Both store access tests
must pass, the read-only SQLite check must print `ok`, and every protected-runtime write test must
remain false.

```console
sudo stat -c '%U:%G %a %n' "$TRADING_HOME" "$REPOSITORY/.env" \
  "$TRADING_HOME/execution.sqlite3" \
  "$TRADING_HOME/paper-observation-screen.lock" \
  "$TRADING_HOME/paper-observation.lock"
sudo stat -c '%U:%G %a %n' "$TRADING_HOME/runtime-builds" "$BUILD_DIRECTORY" \
  "$WHEEL" "$MANIFEST" "$RUNTIME"
sudo -u "$SERVICE_USER" test -r "$TRADING_HOME/execution.sqlite3"
sudo -u "$SERVICE_USER" test -w "$TRADING_HOME/execution.sqlite3"
sudo -u "$SERVICE_USER" test -x "$RUNTIME"
sudo -u "$SERVICE_USER" test -r "$WHEEL"
sudo -u "$SERVICE_USER" test -r "$MANIFEST"
sudo -u "$SERVICE_USER" env -i PATH=/usr/local/bin:/usr/bin:/bin \
  DATABASE="$TRADING_HOME/execution.sqlite3" python3 -c \
  'import os, sqlite3; from pathlib import Path; connection = sqlite3.connect(Path(os.environ["DATABASE"]).as_uri() + "?mode=ro", uri=True); assert connection.execute("PRAGMA quick_check").fetchone() == ("ok",); print("ok")'
while IFS= read -r -d '' path; do
  sudo -u "$SERVICE_USER" test ! -w "$path" || { echo "writable protected runtime: $path" >&2; exit 1; }
done < <(sudo find "$BUILD_DIRECTORY" -print0)
```

Authenticate with the same fixed, secret-free lookup environment used by the unit. If the status
command reports no login, run the login command once, then rerun status. Tokens stay in the private
GitHub CLI configuration, never in the unit.

```console
if ! sudo -u "$SERVICE_USER" env -i HOME="$SERVICE_HOME" GH_CONFIG_DIR="$GH_CONFIG_DIR" \
  XDG_CACHE_HOME="$SERVICE_HOME/.cache" GH_HOST=github.com GH_PROMPT_DISABLED=1 \
  PATH=/usr/local/bin:/usr/bin:/bin gh auth status --hostname github.com; then
  sudo -u "$SERVICE_USER" env -i HOME="$SERVICE_HOME" GH_CONFIG_DIR="$GH_CONFIG_DIR" \
    XDG_CACHE_HOME="$SERVICE_HOME/.cache" GH_HOST=github.com \
    PATH=/usr/local/bin:/usr/bin:/bin \
    gh auth login --hostname github.com --git-protocol https --web
fi
sudo -u "$SERVICE_USER" env -i HOME="$SERVICE_HOME" GH_CONFIG_DIR="$GH_CONFIG_DIR" \
  XDG_CACHE_HOME="$SERVICE_HOME/.cache" GH_HOST=github.com GH_PROMPT_DISABLED=1 \
  PATH=/usr/local/bin:/usr/bin:/bin gh auth status --hostname github.com
```

The private `.env` must contain exactly `TRADING_LAB_MODE=paper`, the same absolute
`TRADING_LAB_HOME` shown above, and nonempty `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` values. The
supervisor rejects missing, extra, malformed, symlinked, wrongly owned, or non-0600 configuration.
It also rejects credential values inherited from another process. Do not add activation or paper
code-commit entries. The generated unit contains no credentials and explicitly blanks both
broker-write opt-in variables. The CLI reads the four allowed values from the repository `.env` after
systemd sets the working directory.
Runtime-verification `git` and `gh` subprocesses receive no broker credentials or write opt-in.
Git ignores inherited `GIT_*` controls. Attestation verification uses explicit `github.com`, fixed
`HOME`, `GH_CONFIG_DIR`, and cache paths. The unit clears every GitHub CLI token variable so the
private `GH_CONFIG_DIR` is the only credential source; the unit contains no token.

Check the exact runtime, manifest, wheel, installed distribution, configuration, interval, and
write-disabled state before installation:

```console
cd "$REPOSITORY"
sudo ./scripts/paper_observation_systemd.sh check "$CAMPAIGN_ID" "$RUNTIME" "$WHEEL" "$MANIFEST" "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP" 600
```

This check requires the repository HEAD and tracked risk configuration to match the runtime build
commit, verifies the GitHub attestations and every installed wheel-owned file, and checks the
store-local lock. It makes no broker or database call. It never falls back to `uv run`, an editable
install, or source-checkout code.

### Boot-enabled systemd service

Render the unit for review, then install and enable the same fixed unit at boot:

```console
sudo ./scripts/paper_observation_systemd.sh render "$CAMPAIGN_ID" "$RUNTIME" "$WHEEL" "$MANIFEST" "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP" 600
sudo ./scripts/paper_observation_systemd.sh install "$CAMPAIGN_ID" "$RUNTIME" "$WHEEL" "$MANIFEST" "$TRADING_HOME" "$SERVICE_USER" "$SERVICE_GROUP" 600
sudo ./scripts/paper_observation_systemd.sh status
sudo ./scripts/paper_observation_systemd.sh logs
sudo systemctl show systematic-trading-lab-paper-observation.service -p MainPID -p ExecMainStatus -p NRestarts
```

The installer first repeats the ownership check. It then runs the same fail-closed preflight as the
service, refuses an active Screen observer,
checks the rendered unit with `systemd-analyze verify`, writes one root-owned unit, runs
`daemon-reload`, and calls `enable --now`. `WantedBy=multi-user.target`
starts it after later boots; `Wants=` and `After=network-online.target` place it after the host's
configured online wait. Output and errors go to journald. The service uses a 600-second cycle and
samples immediately on each start. A reboot just before the next scheduled sample leaves roughly 300
seconds for boot and recovery before the fixed 900-second gap is breached. Software cannot guarantee
that limit during a long provider outage, host outage, boot, DNS failure, or runtime-attestation
failure. Startup still requires live GitHub attestation access; no cached proof lifecycle has been
reviewed. A failed or indeterminate remote verdict never permits an observation.

The service handles terminal states as follows:

| Event | Result |
|---|---|
| Clean host reboot | systemd stops the process group, boot enablement starts it after network-online, and the loop samples immediately after preflight. |
| Unexpected crash or signal | Restart after at least 60 seconds, with no finite start-count limit. |
| Manual service restart | Release and reacquire the same store-local lock, reassess, then sample immediately if the campaign is active. |
| Campaign already complete | Print the immutable assessment and exit 0 without another sample, whether the campaign passed or failed. |
| Invalid runtime, campaign, interval, `.env`, home, store, or journal | Exit 2, remain visibly failed, and do not restart automatically. |
| Missing `gh`, GitHub authentication failure, or local provenance/integrity mismatch | Exit 2, remain failed, and do not restart automatically. |
| Timeout or recognized DNS, connection, rate-limit, or HTTP 5xx attestation failure | Exit 75 without observing, then retry after at least 60 seconds with no finite start-count limit. |
| Lock already held | Exit 2 without a second observer; stop the old runner, then use `systemctl reset-failed` and `systemctl start`. |
| Broker read failure or drift | Record the existing immutable result and continue so later recovery remains visible. |

GitHub CLI does not expose separate stable exit codes for transport failure, a missing attestation,
and a remote policy or signature rejection. Every exit remains fail-closed. The wrapper retries only
a timeout or explicit transport, rate-limit, or server-availability error. Authentication, missing
attestation, policy/signature rejection, and unrecognized failures exit 2. A retryable failure gets
another attempt after at least 60 seconds. `StartLimitIntervalSec=0` disables systemd's finite
start-count limiter, so repeated exit 75 results cannot permanently latch the service off. If an
outage has already failed the 900-second continuity gate, verification and recovery attempts still
continue; a retry never infers a valid attestation or permits an observation before verification.

Use `trading-lab paper assess-observation CAMPAIGN_ID` for the authoritative final exit status. The
supervisor's clean terminal exit means only that no more samples are due; it does not turn a failed
campaign into a pass.

### Optional GNU Screen launcher

Screen remains available for manual diagnosis but is not boot-safe. It launches the same verified
supervisor command and uses the same store-local lock:

```console
./scripts/paper_observation_screen.sh start "$CAMPAIGN_ID" "$RUNTIME" "$WHEEL" "$MANIFEST" "$TRADING_HOME" 600
./scripts/paper_observation_screen.sh status
screen -r systematic-trading-lab-observation
./scripts/paper_observation_screen.sh stop
```

Detach with `Ctrl-A`, then `D`. Do not run Screen while the systemd unit is active.

### Short reboot recovery drill

Run this bounded drill only with a reviewed `main` artifact that has passed runtime verification. Use
a new one-hour campaign and the intended 600-second interval. Do not reuse or edit retained campaign
evidence.

1. Set `CAMPAIGN_ID=paper-reboot-drill-YYYYMMDDHHMM`, rerun the `check` command above, and stop every
   other observer.
2. From `$REPOSITORY`, start the one-hour test campaign with the exact verified runtime:

   ```console
   sudo -u "$SERVICE_USER" env -i HOME=/var/lib/systematic-trading-lab PATH=/usr/local/bin:/usr/bin:/bin TRADING_LAB_MODE=paper TRADING_LAB_HOME="$TRADING_HOME" TRADING_LAB_PAPER_ACTIVATION_ID= TRADING_LAB_PAPER_CODE_COMMIT= "$RUNTIME" paper start-observation "$CAMPAIGN_ID" --risk-config "$REPOSITORY/config/risk/alpaca-paper-v1.json" --maximum-gap-seconds 900 --duration-hours 1
   ```

3. Run the `install` command above with that exact test campaign. Confirm `is-enabled`, `is-active`,
   one nonzero `MainPID`, one matching process, and one held lock:

   ```console
   sudo systemctl is-enabled systematic-trading-lab-paper-observation.service
   sudo systemctl is-active systematic-trading-lab-paper-observation.service
   sudo systemctl show systematic-trading-lab-paper-observation.service -p MainPID -p NRestarts
   sudo systemctl cat systematic-trading-lab-paper-observation.service
   pgrep -a -f "$RUNTIME paper supervise-observation $CAMPAIGN_ID"
   sudo lslocks --output COMMAND,PID,TYPE,PATH | grep -F "$TRADING_HOME/paper-observation.lock"
   ```

4. Record the execution-store identity and the latest pre-reboot assessment:

   ```console
   cat /proc/sys/kernel/random/boot_id
   sudo stat -c '%d:%i' "$TRADING_HOME/execution.sqlite3"
   sudo -u "$SERVICE_USER" env -u APCA_API_KEY_ID -u APCA_API_SECRET_KEY TRADING_LAB_MODE=paper TRADING_LAB_HOME="$TRADING_HOME" TRADING_LAB_PAPER_ACTIVATION_ID= TRADING_LAB_PAPER_CODE_COMMIT= "$RUNTIME" paper assess-observation "$CAMPAIGN_ID"
   ```

5. Reboot the intended VPS and reconnect:

   ```console
   sudo systemctl reboot
   ```

6. Re-run the fixed path assignments from the Linux VPS configuration section. Confirm boot-start
   evidence, the same store identity, one process, and one lock. Follow the journal
   until the first post-reboot observation appears:

   ```console
   cd "$REPOSITORY"
   sudo systemctl is-enabled systematic-trading-lab-paper-observation.service
   sudo systemctl is-active systematic-trading-lab-paper-observation.service
   sudo journalctl -u systematic-trading-lab-paper-observation.service -b --no-pager
   cat /proc/sys/kernel/random/boot_id
   sudo stat -c '%d:%i' "$TRADING_HOME/execution.sqlite3"
   pgrep -a -f "$RUNTIME paper supervise-observation $CAMPAIGN_ID"
   sudo lslocks --output COMMAND,PID,TYPE,PATH | grep -F "$TRADING_HOME/paper-observation.lock"
   ```

7. Run the same `assess-observation` command after the new sample. Confirm the latest observation time
   advanced, `maximum_observed_gap_seconds` is at most 900, `continuity_held` is true, and output still
   reports `broker_writes_allowed: false`.
8. Let the hour finish. Confirm the service becomes inactive after its clean terminal exit and the
   final assessment reports `campaign_complete: true` and `campaign_passed: true`. Preserve the JSON,
   `journalctl -u systematic-trading-lab-paper-observation.service` output, boot ID, store identity,
   process/lock checks, and unit text together as drill evidence.

The drill passes only if boot enablement was present before reboot, the unit starts in the new boot,
the same campaign and store resume, exactly one observer holds the lock, a later sample exists, the
measured gap is no more than 900 seconds, continuity and the final campaign pass, and no activation or
broker-write authority exists. Any failed item fails the drill. Preserve the failure.

### Disable, uninstall, and cleanup

Remove supervision before retiring the VPS or installing a unit for another campaign:

```console
cd "$REPOSITORY"
sudo ./scripts/paper_observation_systemd.sh uninstall
sudo systemctl is-enabled systematic-trading-lab-paper-observation.service
sudo test ! -e /etc/systemd/system/systematic-trading-lab-paper-observation.service
```

`is-enabled` must report disabled or not found. Cleanup refuses to run while the unit file exists or
the service is active. After uninstalling, cleanup remains dry-run-first:

```console
./scripts/cleanup_vps.sh
./scripts/cleanup_vps.sh --execute
./scripts/cleanup_vps.sh --execute --delete-repository
```

The first executing form stops the named Screen session and deletes only ignored credentials,
runtime state, virtual environments, build output, and Python caches inside the validated project.
The last form deletes the validated repository too. Neither form erases broker or GitHub records,
backups, system journals, shell history, or separately preserved drill evidence. Revoke Alpaca keys
separately when retiring the deployment.

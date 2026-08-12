# Operations

1. Set `TRADING_LAB_HOME` to an isolated writable directory when the default is unsuitable.
2. Run `trading-lab doctor`; stop on any failed check.
3. Import offline fixtures with `trading-lab data import-fixture`.
4. Inspect `trading-lab status`, `data describe`, and `data validate`.
5. Preserve the dataset directory and manifest together when moving evidence.

Recovery: artifact directories are authoritative. After moving a disposable `catalog.sqlite3` aside, run `trading-lab data rebuild-catalog`. Never edit an artifact in place. The execution store can list journal-verified `submission-unknown` orders without changing state. The production reader can retain a sanitized immutable 404 from an exact lookup, but that result is historical evidence only. A read-only proof can bind it to later complete clean reconciliation and the unchanged protected controls for operator review. It does not authorize retry. There is no broker process, retry, cancel action, or live recovery procedure in this phase.

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
current status is not ready and every listed blocker remains mandatory. Process opt-in opens only
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

The first sustained campaign uses the Windows task `SystematicTradingLab-PaperObservation` as an
external 10-minute timer. It pins the exact attested runtime and campaign ID, runs from the repository
directory so the ignored `.env` loads, starts missed work when the computer becomes available, wakes
from sleep, and expires at the campaign end. It cannot run while the computer is powered off; any
resulting gap remains evidence. The one-shot command and database remain authoritative, not the task.

### Linux VPS configuration

Stop or disable every other observation runner before moving `execution.sqlite3`. Never synchronize
an active SQLite store between machines. The Screen launcher and systemd service now call the same
packaged supervisor command and contend on
`TRADING_LAB_HOME/paper-observation.lock`, so only one can observe a store. The supervisor also holds
the prior Screen lock name so an observer started before this upgrade blocks the new service.
The campaign-start and one-shot record commands also take these locks.

Use one dedicated, unprivileged service account. The repository and exact attested runtime must
already exist under `/opt/systematic-trading-lab`. Put the wheel and manifest beside the verified
virtual environment:

```text
/opt/systematic-trading-lab/.trading-lab/runtime-builds/FULL_COMMIT/
├── runtime-build-manifest.json
├── systematic_trading_lab-0.1.0-py3-none-any.whl
└── verified-venv/bin/trading-lab
```

Set the fixed paths. Replace only `FULL_COMMIT` and `CAMPAIGN_ID`; use a short test campaign for the
recovery drill below, not the final 168-hour campaign.

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
```

Create the service account and private state directory once. If `.env` already exists, do not run the
`install /dev/null` command; verify its owner and mode instead.

```console
sudo useradd --system --user-group --create-home --home-dir /var/lib/systematic-trading-lab --shell /usr/sbin/nologin "$SERVICE_USER"
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0700 "$TRADING_HOME"
sudo test ! -e "$REPOSITORY/.env"
sudo install -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0600 /dev/null "$REPOSITORY/.env"
sudoedit "$REPOSITORY/.env"
sudo chown "$SERVICE_USER:$SERVICE_GROUP" "$REPOSITORY/.env"
sudo chmod 0600 "$REPOSITORY/.env"
sudo -u "$SERVICE_USER" -H gh auth status
chmod +x scripts/paper_observation_screen.sh scripts/paper_observation_systemd.sh scripts/cleanup_vps.sh
```

If the GitHub check reports no login, authenticate that service account with
`sudo -u "$SERVICE_USER" -H gh auth login --hostname github.com --git-protocol https --web`, then
rerun `gh auth status`. GitHub credentials stay in the service account's home, not the repository or
unit.

The private `.env` must contain exactly `TRADING_LAB_MODE=paper`, the same absolute
`TRADING_LAB_HOME` shown above, and nonempty `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` values. The
supervisor rejects missing, extra, malformed, symlinked, wrongly owned, or non-0600 configuration.
It also rejects credential values inherited from another process. Do not add activation or paper
code-commit entries. The generated unit contains no credentials and explicitly blanks both
broker-write opt-in variables. The CLI reads the four allowed values from the repository `.env` after
systemd sets the working directory.
Runtime-verification `git` and `gh` subprocesses receive no broker credentials or write opt-in.

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

The installer runs the same fail-closed preflight as the service, refuses an active Screen observer,
checks the rendered unit with `systemd-analyze verify`, writes one root-owned unit, runs
`daemon-reload`, and calls `enable --now`. `WantedBy=multi-user.target`
starts it after later boots; `Wants=` and `After=network-online.target` place it after the host's
configured online wait. Output and errors go to journald. The service uses a 600-second cycle and
samples immediately on each start. A reboot just before the next scheduled sample leaves roughly 300
seconds for boot and recovery before the fixed 900-second gap is breached. Software cannot guarantee
that limit during a long provider outage, host outage, boot, DNS failure, or runtime-attestation
failure.

The service handles terminal states as follows:

| Event | Result |
|---|---|
| Clean host reboot | systemd stops the process group, boot enablement starts it after network-online, and the loop samples immediately after preflight. |
| Unexpected crash or signal | Restart after 30 seconds, limited to three starts per 900 seconds. |
| Manual service restart | Release and reacquire the same store-local lock, reassess, then sample immediately if the campaign is active. |
| Campaign already complete | Print the immutable assessment and exit 0 without another sample, whether the campaign passed or failed. |
| Invalid runtime, campaign, interval, `.env`, home, store, or journal | Exit 2, remain visibly failed, and do not restart automatically. |
| Lock already held | Exit 2 without a second observer; stop the old runner, then use `systemctl reset-failed` and `systemctl start`. |
| Broker read failure or drift | Record the existing immutable result and continue so later recovery remains visible. |

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

Run this bounded drill only after the branch has merged and a new `main` artifact has passed runtime
verification. Use a new one-hour campaign and the intended 600-second interval. Do not reuse or edit
Week 1 evidence, and do not use the final campaign ID.

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
broker-write authority exists. Any failed item fails the drill. Preserve the failure and do not start
the final campaign.

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

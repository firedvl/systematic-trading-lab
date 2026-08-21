# Intraday Exposed 002 host investigation

Status: `CAUSE UNDETERMINED`.

This read-only investigation sought surviving host evidence for the Exposed 002 runner process that
disappeared while run `ie002r-f0718fce63d8b518e7601c7e` was claimed. It did not open market data,
June data, strategy results beyond the committed terminal report, protected state, PAPER or broker
state, or `strategic-allocation-21`. It changed no Exposed 002 evidence.

## Surviving time evidence

The last completed create-only report has birth and modification time
`2026-08-21T03:47:33Z`. The terminal recovery database modification time is
`2026-08-21T19:26:12Z`. These timestamps bracket the missing process but do not establish its claim
or exit time. The frozen runtime schema stored no attempt timestamp, PID, hostname, heartbeat,
stdout, stderr, exit status, or resource measurement.

## Host checks

- macOS reported the current boot began on 2026-08-15, with no reboot in the incident bracket.
- A targeted kernel and unified-log search after the last report found no matching Python runner
  OOM kill, memory-pressure kill, panic, disk-full error, I/O error, or filesystem error.
- One later high-memory-watermark report belonged to `IMTransferAgent`, not Python or the research
  runner. It is unrelated evidence.
- Power-management logs showed release of an idle-sleep preventer at 2026-08-21T03:49:19Z, but no
  tied sleep, wake, restart, or runner termination event. It does not establish causality.
- Crash and core metadata contained no Python or runner artifact created between the last completed
  report and recovery.
- Current disk state had about 73 GiB free and no inode pressure. No historical disk measurement
  survived.
- No process currently held the campaign lock or matched the runner. This is expected after the
  disappearance and is not cause evidence.

The completed narrow unified-log query covered about the first 32 minutes after the last report. A
broader 15.6-hour query exceeded the command time limit, so the host-log search was not exhaustive.
No checked source supports attributing the event to OOM, sleep, reboot, disk exhaustion, a Python
crash, or an operator action.

## Disposition

Keep the terminal report conclusion unchanged: `CAUSE UNDETERMINED`.

Prospective runners must record an append-only attempt identity, immutable run fingerprint, source
SHA, UTC start and end, hostname, PID, stdout, stderr, exit status when known, lease heartbeats, and
lightweight memory, RSS, disk, load, and duration telemetry. This evidence cannot repair, retry, or
reinterpret Exposed 002.

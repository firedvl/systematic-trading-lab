# Program 005 private Alpaca data

Program 005 uses the public repository as a reproducibility recipe and keeps every provider market
observation under the Git-ignored `.trading-lab/program-005-free-alpaca/` root. Raw responses,
canonical OHLCV, analytical OHLCV, checkpoints, private manifests, and backups are private data.
Do not publish or commit them.

The public recipe fixes Alpaca Basic historical SIP, `5Min`, `feed=sip`, `limit=10000`,
`asof=2026-07-31`, inclusive bounds, and paired `adjustment=raw` and
`adjustment=split,spin-off` GET chains for IWM, MDY, SPY, XLB, XLE, XLF, XLI, XLK, XLP, XLRE,
XLU, XLV, and XLY. Another authorized user can recreate the contract with their own Alpaca account
and credentials; no private dataset bytes are included in Git.

## Access and credentials

Use an Alpaca account whose current terms and entitlements permit the requested private personal
research use and historical SIP access. Keep credentials in the acquisition process environment
only:

```console
read -r PROGRAM_005_ALPACA_API_KEY_ID
read -rs PROGRAM_005_ALPACA_API_SECRET_KEY
export PROGRAM_005_ALPACA_API_KEY_ID PROGRAM_005_ALPACA_API_SECRET_KEY
```

Do not place these variables in `.env`, a manifest, a command argument, a log, or source control.
Research workers reject them, and non-broker subprocess environments remove them.

## Commands

Credential-free preflight derives and validates the exact request set without contacting Alpaca:

```console
uv run trading-lab data acquire program-005 preflight --scope qualification
uv run trading-lab data acquire program-005 preflight --scope full
```

After the v2 proposal and its finding-free review are merged, the user must separately authorize the
exact root printed in the readiness handoff. Activation derives the authority from the fixed
repository artifacts; it does not accept an operator-written authority file:

```console
uv run trading-lab data acquire program-005 activate \
  --scope qualification \
  --authorization-root EXACT_USER_AUTHORIZED_ROOT

uv run trading-lab data acquire program-005 run \
  --scope qualification \
  --authorization-root EXACT_USER_AUTHORIZED_ROOT
```

The root is the external authorization input. A newly computed root for changed artifacts has no
user authority. The loader reconstructs the authority from the exact proposal, review, scientific
contract, and implementation manifest, then requires canonical equality with the create-only file
under `.trading-lab/program-005-free-alpaca/qualification/active-authority.json`. It also requires a
clean `HEAD == main == origin/main`, rejects changes to authority-relevant source after review, and
revalidates the whole chain under the run lock before publishing the one-use claim or loading
credentials. Later control-only commits may move `main` when the reviewed implementation bytes stay
unchanged.

Artifact hashes prove identity; they do not grant authority by themselves. Computing or rehashing a
proposal, review, or authority cannot transfer the user's authorization to those new bytes. The
local tool assumes the invoking user and host administrator are trusted, as stated in the repository
threat model. Deleting or replacing the complete local authority store invalidates its evidence; it
is not a supported reset or a new authorization.

The full-scope preflight builds the future deterministic request set, but full execution remains
fail-closed until exact qualification dataset bytes, its terminal receipt, and a finding-free
independent review are bound and enforced. A later reviewed implementation may enable that scope;
provider corrections must create a new identity rather than silently refreshing a frozen dataset.

The one-use qualification covers 22 sessions, 13 symbols, 26 paired chains, 28 expected responses,
60 maximum responses, 64 MiB, one credential load, no retries, and 120 requests per minute. The full
range is June 26, 2020 through July 31, 2026: 1,531 XNYS sessions and 3,093,636 expected paired rows.
It expects about 3,046 responses when each non-pagination chain uses one page. Plan for roughly
0.4-0.8 GiB of source JSON and an 8 GiB working-disk reservation.

The generated public manifest contains dataset identity, contract values, structural counts, and
hashes only. Verify its canonical hashes against the private frozen files. The private source
manifest additionally binds exact request pages, timestamps, hashes, and storage locations and must
remain private.

## Repository safety

The required repository scan rejects Program 005 market-data paths, raw or canonical bar-shaped
JSON, and the dedicated credential names in environment, shell-export, or JSON assignment syntax.
The public policy, plan, contract, ledger, proposal, and review paths are narrowly listed, but their
content is still checked for observations and credentials. Tests use synthetic values and responses
only.

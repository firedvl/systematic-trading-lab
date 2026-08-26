"""Acquisition-only Program 002 command; it never launches research work."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from .fingerprints import canonicalize
from .program_002_acquisition import (
    HistoricalHttpClient,
    Program002AcquisitionError,
    acquire_quote_segments,
    acquire_role_segments,
    acquisition_authority_preflight,
    acquisition_credentials,
    bar_segments,
    derive_quote_costs_from_artifacts,
    load_plan,
    provider_contract_preflight,
    publish_quote_costs,
    publish_role_dataset_from_artifacts,
    publish_volume_context_projection,
    quote_segment_ids,
    quote_segments,
)
from .storage import StorageLayout


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m systematic_trading_lab.program_002_acquisition_cli"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--data-home", type=Path)
    parser.add_argument("--acquisition-attempt-id")
    parser.add_argument("--source-dataset-id")
    parser.add_argument(
        "--role",
        choices=("exposed-context-only", "exposed-block-1", "exposed-block-2", "exposed-block-3"),
    )
    parser.add_argument(
        "action",
        choices=(
            "preflight",
            "acquire-bars",
            "acquire-quotes",
            "derive-publish-costs",
            "publish-context-projection",
        ),
    )
    parsed = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        plan = load_plan(parsed.repository)  # Strict plan and authority before credentials.
        provider_contract_preflight(plan)
        acquisition_authority_preflight(plan)
        if parsed.action == "preflight":
            print(
                json.dumps(
                    canonicalize(
                        {
                            "plan_sha256": plan.sha256,
                            "authority_id": plan.authority.authority_id,
                            "status": "preflight-passed",
                        }
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if parsed.acquisition_attempt_id is None:
            raise Program002AcquisitionError("acquisition actions require --acquisition-attempt-id")
        if parsed.action == "publish-context-projection":
            if parsed.data_home is None:
                raise Program002AcquisitionError("publish-context-projection requires --data-home")
            source_dataset_id = parsed.source_dataset_id
            if source_dataset_id is None:
                raise Program002AcquisitionError(
                    "publish-context-projection requires --source-dataset-id"
                )
            path, artifact, created = publish_volume_context_projection(
                plan, StorageLayout(parsed.data_home), source_dataset_id
            )
            print(
                json.dumps(
                    canonicalize(
                        {
                            "path": str(path),
                            "created": created,
                            "projection_id": artifact["projection_fingerprint"],
                            "projection_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if parsed.action == "derive-publish-costs":
            if parsed.data_home is None:
                raise Program002AcquisitionError("derive-publish-costs requires --data-home")
            layout = StorageLayout(parsed.data_home)
            artifact = derive_quote_costs_from_artifacts(
                plan,
                layout,
                quote_segment_ids(plan, parsed.acquisition_attempt_id),
                acquisition_attempt_id=parsed.acquisition_attempt_id,
            )
            path, created = publish_quote_costs(
                layout, artifact, plan, acquisition_attempt_id=parsed.acquisition_attempt_id
            )
            print(
                json.dumps(
                    canonicalize(
                        {
                            "path": str(path),
                            "created": created,
                            "quote_artifact_id": path.stem,
                            "quote_artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                    ),
                    sort_keys=True,
                )
            )
            return 0
        if parsed.action == "acquire-bars":
            if parsed.data_home is None or parsed.role is None:
                raise Program002AcquisitionError("acquire-bars requires --data-home and --role")
            segments = bar_segments(plan, parsed.role)
            key, secret = acquisition_credentials()
            completed = acquire_role_segments(
                plan,
                parsed.role,
                StorageLayout(parsed.data_home),
                HistoricalHttpClient(key, secret, plan, segments).get,
                acquisition_attempt_id=parsed.acquisition_attempt_id,
            )
            published = publish_role_dataset_from_artifacts(
                plan,
                parsed.role,
                completed,
                StorageLayout(parsed.data_home),
                datetime.now(UTC),
                acquisition_attempt_id=parsed.acquisition_attempt_id,
            )
            print(
                json.dumps(
                    canonicalize({"role": parsed.role, "dataset_id": published.dataset_id}),
                    sort_keys=True,
                )
            )
            return 0
        if parsed.action == "acquire-quotes":
            if parsed.data_home is None:
                raise Program002AcquisitionError("acquire-quotes requires --data-home")
            segments = quote_segments(plan)
            key, secret = acquisition_credentials()
            completed = acquire_quote_segments(
                plan,
                StorageLayout(parsed.data_home),
                HistoricalHttpClient(key, secret, plan, segments).get,
                acquisition_attempt_id=parsed.acquisition_attempt_id,
            )
            print(json.dumps(canonicalize({"completed_quote_windows": completed}), sort_keys=True))
            return 0
        raise Program002AcquisitionError("unrecognized acquisition action")
    except (OSError, Program002AcquisitionError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return os.EX_USAGE


if __name__ == "__main__":
    raise SystemExit(main())

"""Closed identities for source-reviewed intraday campaigns."""

from __future__ import annotations

from dataclasses import dataclass

INTRADAY_CAMPAIGN_V1_ID = "intraday-research-v1"
INTRADAY_CAMPAIGN_V2_ID = "intraday-research-v2"
INTRADAY_FOUNDATION_LOCK_SHA256 = "d6d60aa5d93644dd3bf932ef84f6793bab6d33992659ed48e968850c6673c00d"


@dataclass(frozen=True)
class IntradayCampaignContract:
    campaign_id: str
    plan_fingerprint: str
    foundation_commit: str
    lock_sha256: str
    surface_manifest_name: str
    surface_manifest_schema: str
    execution_enabled: bool


INTRADAY_CAMPAIGN_CONTRACTS = (
    IntradayCampaignContract(
        campaign_id=INTRADAY_CAMPAIGN_V1_ID,
        plan_fingerprint="ce81be36d02cc15f421390bf3d3787714bb0b025797ccfb8de2c1d1236052c1a",
        foundation_commit="b1774f547da2976348430b820faf2ebdacdf46af",
        lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
        surface_manifest_name="intraday_campaign_v1_surface.json",
        surface_manifest_schema="intraday-campaign-v1-surface-manifest-v1",
        execution_enabled=False,
    ),
    IntradayCampaignContract(
        campaign_id=INTRADAY_CAMPAIGN_V2_ID,
        plan_fingerprint="52db8a27fa4ff86865ab69b6bd7456899329ef3b861a582e59ab32904c03c122",
        foundation_commit="f3d7ee7d86c3a02b52c09270a6399aa1bf5f78b7",
        lock_sha256=INTRADAY_FOUNDATION_LOCK_SHA256,
        surface_manifest_name="intraday_campaign_v2_surface.json",
        surface_manifest_schema="intraday-campaign-v2-surface-manifest-v1",
        execution_enabled=True,
    ),
)
RESERVED_INTRADAY_CAMPAIGN_IDS = frozenset(
    contract.campaign_id for contract in INTRADAY_CAMPAIGN_CONTRACTS
)


def get_intraday_campaign_contract(campaign_id: str) -> IntradayCampaignContract:
    for contract in INTRADAY_CAMPAIGN_CONTRACTS:
        if contract.campaign_id == campaign_id:
            return contract
    raise ValueError(f"unsupported intraday campaign: {campaign_id}")

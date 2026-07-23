"""Server-enforced trial allowance for actual large-model invocations.

The quota belongs to one workspace's trial snapshot, never to a particular
provider, model, browser request, or product-plan feature flag.  The AI
gateway calls this module immediately before it persists an external attempt;
therefore Agent tool loops, retries, and configured fallbacks each consume one
unit, while local route/configuration failures do not.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Organization, utcnow


TRIAL_LLM_CALL_LIMIT = 1_000
TRIAL_LLM_CALL_QUOTA_EXHAUSTED_CODE = "trial_llm_call_quota_exhausted"


class TrialQuotaError(RuntimeError):
    """A stable state error surfaced by the AI gateway without vendor detail."""


def reserve_trial_llm_call(session: Session, *, organization_id: str) -> None:
    """Reserve one trial large-model call in the caller's current transaction.

    The conditional update is the concurrency boundary.  It is intentionally
    left uncommitted so the gateway can commit it atomically with the matching
    ``ApiInvocation`` record.  If writing that record fails before any network
    request, rolling back also releases the reservation.

    Active paid workspaces do not have this trial cap.  Expired/suspended
    workspaces are blocked here as well, so a background job queued before a
    plan change cannot make a later model call outside the allowed access.
    """

    organization = session.get(Organization, organization_id)
    if organization is None:
        raise TrialQuotaError("organization_not_found")

    status = organization.plan_status
    if status == "active":
        return
    if status == "expired":
        raise TrialQuotaError("trial_expired")
    if status != "trial":
        raise TrialQuotaError("organization_access_suspended")

    now = utcnow()
    is_within_trial_window = (
        (Organization.trial_ends_at.is_(None))
        | (Organization.trial_ends_at > now)
    )
    reservation = session.execute(
        update(Organization)
        .where(
            Organization.id == organization_id,
            Organization.plan_status == "trial",
            is_within_trial_window,
            Organization.trial_llm_call_used < Organization.trial_llm_call_limit,
        )
        .values(
            trial_llm_call_used=Organization.trial_llm_call_used + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if reservation.rowcount == 1:
        return

    # A plan administrator can switch status while a request is resolving its
    # route. Refresh only this workspace so we return the correct stable
    # reason instead of treating an active plan as quota exhaustion.
    session.expire(organization)
    if organization.plan_status == "active":
        return
    trial_ends_at = _as_utc(organization.trial_ends_at)
    if organization.plan_status == "expired" or (
        organization.plan_status == "trial"
        and trial_ends_at is not None
        and trial_ends_at <= now
    ):
        raise TrialQuotaError("trial_expired")
    if organization.plan_status != "trial":
        raise TrialQuotaError("organization_access_suspended")
    raise TrialQuotaError(TRIAL_LLM_CALL_QUOTA_EXHAUSTED_CODE)


def _as_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite's naive timestamp round-trip for a safe comparison."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def trial_llm_call_snapshot(
    organization: Organization,
    *,
    plan_status: str,
) -> tuple[int | None, int | None, int | None]:
    """Return safe display values for the current trial, if applicable."""

    if plan_status != "trial":
        return None, None, None
    limit = max(0, int(organization.trial_llm_call_limit))
    used = max(0, int(organization.trial_llm_call_used))
    return limit, used, max(0, limit - used)


__all__ = [
    "TRIAL_LLM_CALL_LIMIT",
    "TRIAL_LLM_CALL_QUOTA_EXHAUSTED_CODE",
    "TrialQuotaError",
    "reserve_trial_llm_call",
    "trial_llm_call_snapshot",
]

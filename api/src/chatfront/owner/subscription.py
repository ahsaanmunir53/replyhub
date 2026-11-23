"""ReplyHub plans: which features a business pays for, and for how long.

A new business is on the trial: the assistant answers one chat, a handful of times, for a few
days, so the owner sees what it does before paying. Basic answers customers on WhatsApp by the
owner's rules; Pro adds the shared inbox, the owner's own WhatsApp commands and the website
reports; Business adds staff logins, broadcasts, and Instagram and Messenger. Each paid plan
comes with a monthly number of assistant replies, so one busy or abusive chat cannot run up the
model bill.

The plan is the operator's to set (POST /internal/plan), never the owner's, since it follows
what the business paid; the owner can only ask for one (POST /api/owner/plan/request). With
selling on (Chatfront, COMMERCE=true) every feature is on and nothing is counted, as before
plans existed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import StrEnum

from chatfront.core.models import Tenant

PLAN_KEY = "plan"
PAID_UNTIL = "paid_until"  # ISO date: the last day the payment covers
PLAN_REQUEST = "plan_request"  # {"plan": ..., "at": ISO time}: the owner asked to pay
VERIFIED = "verified"  # the operator connected the business's WhatsApp number
GRACE_DAYS = 3  # replies carry on this long after paid_until, while the renewal comes in
MONTH_DAYS = 30


class Plan(StrEnum):
    TRIAL = "trial"
    BASIC = "basic"
    PRO = "pro"
    BUSINESS = "business"


PAID = (Plan.BASIC, Plan.PRO, Plan.BUSINESS)


class Feature(StrEnum):
    ASSISTANT = "assistant"  # replies on WhatsApp and the website chat by the owner's rules
    RULES = "rules"
    INBOX = "inbox"  # every chat in one place, and the owner replies there
    OWNER_WHATSAPP = "owner_whatsapp"  # "aaj ka scene" and other commands from the owner's phone
    REPORTS = "reports"  # the website's orders and the daily report
    TEAM = "team"  # staff logins
    BROADCASTS = "broadcasts"  # offers to customers who said yes
    INSTAGRAM = "instagram"
    MESSENGER = "messenger"


_BASIC = frozenset({Feature.ASSISTANT, Feature.RULES})
_PRO = _BASIC | {Feature.INBOX, Feature.OWNER_WHATSAPP, Feature.REPORTS}
PLANS: dict[Plan, frozenset[Feature]] = {
    # The trial shows the inbox too, so the owner sees the trial chat the way Pro would.
    Plan.TRIAL: _BASIC | {Feature.INBOX},
    Plan.BASIC: _BASIC,
    Plan.PRO: _PRO,
    Plan.BUSINESS: _PRO | {Feature.TEAM, Feature.BROADCASTS, Feature.INSTAGRAM, Feature.MESSENGER},
}
EVERYTHING = frozenset(Feature)
# The channels a plan must include before their messages are answered; WhatsApp and the
# website chat come with every plan.
CHANNEL_FEATURES = {"instagram": Feature.INSTAGRAM, "messenger": Feature.MESSENGER}


def plan_of(tenant: Tenant) -> Plan:
    value = (tenant.profile or {}).get(PLAN_KEY)
    return Plan(value) if value in set(Plan) else Plan.TRIAL


def features_of(tenant: Tenant, *, commerce: bool) -> frozenset[Feature]:
    return EVERYTHING if commerce else PLANS[plan_of(tenant)]


def answers_channel(tenant: Tenant, channel: str, *, commerce: bool) -> bool:
    needed = CHANNEL_FEATURES.get(channel)
    return needed is None or needed in features_of(tenant, commerce=commerce)


def paid_until(tenant: Tenant) -> date | None:
    value = (tenant.profile or {}).get(PAID_UNTIL)
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def lapsed(tenant: Tenant, today: date) -> bool:
    """A paid plan whose payment ran out more than the grace days ago. A paid plan without a
    date (set before dates existed) never lapses."""
    until = paid_until(tenant)
    return (
        plan_of(tenant) in PAID and until is not None and today > until + timedelta(days=GRACE_DAYS)
    )


def extended(tenant: Tenant, today: date, months: int) -> date:
    """The new last paid day: months more from today, or from the current end if still ahead,
    so paying early never loses days."""
    until = paid_until(tenant)
    start = until if until is not None and until >= today else today
    return start + timedelta(days=MONTH_DAYS * months)


def requested(tenant: Tenant) -> tuple[Plan, datetime] | None:
    asked = (tenant.profile or {}).get(PLAN_REQUEST) or {}
    try:
        return Plan(asked["plan"]), datetime.fromisoformat(asked["at"])
    except (KeyError, TypeError, ValueError):
        return None


def allowance(plans: str, plan: Plan) -> int:
    """The monthly assistant replies a paid plan includes, from the setting
    "basic=1500,pro=4000,business=10000"."""
    for part in plans.split(","):
        name, _, value = part.partition("=")
        if name.strip() == plan.value and value.strip().isdigit():
            return int(value)
    return 0


def prices(text: str) -> dict[str, str]:
    """What each plan costs, as the operator writes it: "basic=AED 99 a month;pro=...".
    Shown to the owner as written; nothing is charged here."""
    found: dict[str, str] = {}
    for part in text.split(";"):
        name, _, value = part.partition("=")
        if name.strip() in {p.value for p in PAID} and value.strip():
            found[name.strip()] = value.strip()[:60]
    return found

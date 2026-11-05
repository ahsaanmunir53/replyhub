"""ReplyHub plans: which features a business pays for. Basic answers customers on WhatsApp by
the owner's rules; Pro adds the shared inbox, the owner's own WhatsApp commands and the
website reports; Business adds staff logins, broadcasts, and Instagram and Messenger.

The plan is the operator's to set (POST /internal/plan), never the owner's, since it follows
what the business paid. With selling on (Chatfront, COMMERCE=true) every feature is on, as
before plans existed.
"""

from __future__ import annotations

from enum import StrEnum

from chatfront.core.models import Tenant

PLAN_KEY = "plan"


class Plan(StrEnum):
    BASIC = "basic"
    PRO = "pro"
    BUSINESS = "business"


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
    return Plan(value) if value in set(Plan) else Plan.BASIC


def features_of(tenant: Tenant, *, commerce: bool) -> frozenset[Feature]:
    return EVERYTHING if commerce else PLANS[plan_of(tenant)]


def answers_channel(tenant: Tenant, channel: str, *, commerce: bool) -> bool:
    needed = CHANNEL_FEATURES.get(channel)
    return needed is None or needed in features_of(tenant, commerce=commerce)

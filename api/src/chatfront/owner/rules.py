"""The owner's rules for the assistant (ReplyHub): what the business is, its timings and
address, how customers buy, its returns and other policies, its own questions and answers,
the tone to reply in and what never to say. The assistant reads them as the business details;
it answers from them and from the catalog, and passes on to the owner what they do not cover.

They live in the tenant's profile, beside the keys the rest of the app already reads (hours,
delivery, returns, policies), so the owner's WhatsApp assistant and the MCP tools see them too.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from chatfront.core.models import Tenant

MAX_FAQS = 40
# The profile keys the rules write. hours, delivery, returns and policies are shared with
# the rest of the app; the others are the assistant's own.
TEXT_KEYS = (
    "about",
    "hours",
    "address",
    "delivery",
    "how_to_order",
    "returns",
    "policies",
    "avoid",
)
FAQS, TONE = "faqs", "tone"
Tone = Literal["friendly", "formal", "brief"]
_TONES: dict[str, str] = {
    "friendly": "warm and friendly",
    "formal": "polite and formal",
    "brief": "brief and to the point",
}


class Faq(BaseModel):
    question: str = Field(min_length=1, max_length=200)
    answer: str = Field(min_length=1, max_length=600)


class Rules(BaseModel):
    about: str = Field("", max_length=500)
    hours: str = Field("", max_length=300)
    address: str = Field("", max_length=300)
    delivery: str = Field("", max_length=500)
    how_to_order: str = Field("", max_length=500)
    returns: str = Field("", max_length=500)
    policies: str = Field("", max_length=1000)
    avoid: str = Field("", max_length=500)
    tone: Tone = "friendly"
    faqs: list[Faq] = Field(default_factory=list, max_length=MAX_FAQS)


def rules_of(tenant: Tenant) -> Rules:
    profile = tenant.profile or {}
    tone = profile.get(TONE)
    return Rules(
        **{key: str(profile.get(key) or "") for key in TEXT_KEYS},
        tone=tone if tone in _TONES else "friendly",
        faqs=[Faq.model_validate(f) for f in profile.get(FAQS) or []][:MAX_FAQS],
    )


def _one_line(text: str) -> str:
    return " ".join(text.split())


def detail_lines(tenant: Tenant) -> list[str]:
    """The rules the profile's shared keys do not already give, as business-detail lines.
    hours, delivery, returns and policies are written by shop_details itself."""
    profile = tenant.profile or {}
    lines: list[str] = []
    for key, label in (
        ("about", "About"),
        ("address", "Address"),
        ("how_to_order", "How to buy"),
    ):
        if value := _one_line(str(profile.get(key) or "")):
            lines.append(f"{label}: {value}")
    faqs = [Faq.model_validate(f) for f in profile.get(FAQS) or []][:MAX_FAQS]
    if faqs:
        lines.append("The owner's own answers (give them when a customer asks the same):")
        lines += [f"- Q: {_one_line(f.question)} A: {_one_line(f.answer)}" for f in faqs]
    if avoid := _one_line(str(profile.get("avoid") or "")):
        lines.append(f"Never say or promise: {avoid}")
    if (tone := profile.get(TONE)) in _TONES:
        lines.append(f"Tone the owner wants: {_TONES[tone]}")
    return lines

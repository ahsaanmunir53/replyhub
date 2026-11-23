"""The owner's rules for the assistant (ReplyHub): what the business is, its timings and
address, how customers buy, its returns and other policies, its own questions and answers,
the tone to reply in and what never to say. The assistant reads them as the business details;
it answers from them and from the catalog, and passes on to the owner what they do not cover.

They live in the tenant's profile, beside the keys the rest of the app already reads (hours,
delivery, returns, policies), so the owner's WhatsApp assistant and the MCP tools see them too.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from chatfront.channels.models import Message
from chatfront.channels.types import Kind
from chatfront.core.i18n import t
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


def detail_lines(tenant: Tenant, asked: str | None = None) -> list[str]:
    """The rules the profile's shared keys do not already give, as business-detail lines.
    hours, delivery, returns and policies are written by shop_details itself. With the
    customer's question, a long list of the owner's answers is cut to the closest ones."""
    profile = tenant.profile or {}
    lines: list[str] = []
    for key, label in (
        ("about", "About"),
        ("address", "Address"),
        ("how_to_order", "How to buy"),
    ):
        if value := _one_line(str(profile.get(key) or "")):
            lines.append(f"{label}: {value}")
    faqs = relevant_faqs([Faq.model_validate(f) for f in profile.get(FAQS) or []][:MAX_FAQS], asked)
    if faqs:
        lines.append("The owner's own answers (give them when a customer asks the same):")
        lines += [f"- Q: {_one_line(f.question)} A: {_one_line(f.answer)}" for f in faqs]
    if avoid := _one_line(str(profile.get("avoid") or "")):
        lines.append(f"Never say or promise: {avoid}")
    if (tone := profile.get(TONE)) in _TONES:
        lines.append(f"Tone the owner wants: {_TONES[tone]}")
    return lines


# -- answering without the model ------------------------------------------------------------
#
# A customer who asks what the owner already answered gets the owner's own words at once: no
# model call, no tokens, and no chance of the model rephrasing a price or a timing wrongly.
# Only a close match counts; anything unsure goes to the model as before.

FAQ_BUDGET = 2400  # characters of the owner's answers sent with every model call, at most
FAQ_SHOWN = 8  # when there are more than fit, the ones closest to the question
QUICK_MAX_CHARS = 120  # longer messages usually ask several things: the model takes them
_MATCH = 0.6
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "is",
        "are",
        "am",
        "was",
        "do",
        "does",
        "did",
        "you",
        "your",
        "yours",
        "u",
        "ur",
        "i",
        "me",
        "my",
        "we",
        "our",
        "us",
        "it",
        "its",
        "of",
        "to",
        "for",
        "in",
        "on",
        "at",
        "by",
        "with",
        "and",
        "or",
        "can",
        "could",
        "will",
        "would",
        "please",
        "pls",
        "plz",
        "kindly",
        "hi",
        "hello",
        "hey",
        "dear",
        "sir",
        "madam",
        "ji",
        "bhai",
        "what",
        "whats",
        "how",
        "where",
        "when",
        "which",
        "who",
        "tell",
        "know",
        "about",
        "there",
        "any",
        "some",
        "this",
        "that",
        "kya",
        "hai",
        "hain",
        "hy",
        "he",
        "ha",
        "ka",
        "ki",
        "ke",
        "ko",
        "se",
        "aap",
        "ap",
        "apka",
        "apki",
        "apke",
        "mein",
        "mujhe",
        "mujhy",
        "hum",
        "batao",
        "btao",
        "bataen",
        "batain",
        "bta",
        "yeh",
        "ye",
        "wo",
        "woh",
    }
)
_THANKS = frozenset(
    {
        "thanks",
        "thank you",
        "thankyou",
        "thanks a lot",
        "thank u",
        "thx",
        "ty",
        "shukriya",
        "shukria",
        "bohat shukriya",
        "jazakallah",
        "jazakallah khair",
        "شكرا",
        "شكرا جزيلا",
        "شکریہ",
        "بہت شکریہ",
        "धन्यवाद",
        "शुक्रिया",
        "ধন্যবাদ",
    }
)
_THANKS_MARKS = frozenset("👍🙏❤️💯👌")


def content_words(text: str) -> set[str]:
    found = set()
    for word in _WORD.findall(text.lower()):
        if word in _STOP or (len(word) < 2 and not word.isdigit()):
            continue
        found.add(word[:-1] if len(word) > 3 and word.endswith("s") else word)
    return found


def _score(asked: set[str], question: str) -> float:
    words = content_words(question)
    if not asked or not words:
        return 0.0
    return len(asked & words) / len(asked | words)


def says_thanks(text: str) -> bool:
    plain = " ".join(_WORD.findall(text.lower()))
    marks = {c for c in text if not c.isspace()}
    return plain in _THANKS or (not plain and bool(marks) and marks <= _THANKS_MARKS)


def faq_answer(tenant: Tenant, text: str) -> str | None:
    """The owner's answer to the question the customer asked, when one clearly matches."""
    if len(text) > QUICK_MAX_CHARS:
        return None
    asked = content_words(text)
    faqs = [Faq.model_validate(f) for f in (tenant.profile or {}).get(FAQS) or []][:MAX_FAQS]
    scored = sorted(((_score(asked, f.question), f) for f in faqs), key=lambda p: -p[0])
    if not scored or scored[0][0] < _MATCH:
        return None
    if len(scored) > 1 and scored[1][0] >= _MATCH and scored[0][0] - scored[1][0] < 0.1:
        return None  # two of the owner's answers fit about as well: let the model choose
    return scored[0][1].answer


def quick_answer(tenant: Tenant, message: Message, lang: str) -> str | None:
    """A reply that needs no model: a thank-you, or the owner's own answer."""
    if message.kind != Kind.TEXT or not message.body:
        return None
    text = message.body.strip()
    if says_thanks(text):
        return t("reply.welcome", lang)
    return faq_answer(tenant, text)


def relevant_faqs(faqs: list[Faq], asked: str | None) -> list[Faq]:
    """All the owner's answers when they are short; else the ones closest to the question."""
    if asked is None or sum(len(f.question) + len(f.answer) for f in faqs) <= FAQ_BUDGET:
        return faqs
    words = content_words(asked)
    ranked = sorted(
        enumerate(faqs),
        key=lambda p: (-len(words & content_words(p[1].question + " " + p[1].answer)), p[0]),
    )
    return [f for _, f in ranked[:FAQ_SHOWN]]

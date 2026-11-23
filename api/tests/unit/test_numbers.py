

def test_a_lone_letter_is_not_a_lakh_or_a_million() -> None:
    """'Size S, M, L or XL?' has no numbers in it; '5 k' and '2 lakh' still do."""
    from chatfront.shield.answer_check import Facts, unsupported

    facts = Facts(digits=2)
    assert unsupported("Kaunsa size chahiye? (S, M, L, XL)", facts, "ur-Latn") == []
    assert unsupported("price 5 k only", facts, "ur-Latn") != []

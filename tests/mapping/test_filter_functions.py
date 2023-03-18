import pytest

from id_translation.mapping import filter_functions as mf

KEYWORDS = ("or", "ee")


def test__parse_where_arg():
    with pytest.raises(ValueError):
        mf._parse_where_args("bad-arg")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        mf._parse_where_args(())

    assert mf._parse_where_args(("name", "candidate", "context")) == ("name", "candidate", "context")
    assert mf._parse_where_args(("name", "context")) == ("name", "context")
    assert mf._parse_where_args("name") == ("name",)


@pytest.mark.parametrize(
    "name, context, candidates, where, expected",
    [
        # where: name
        ("name-suf", "", {"cand0", "cand1"}, "name", {"cand0", "cand1"}),
        ("name", "", {"cand0-suf", "cand1-suf"}, "name", set()),
        # where: candidate
        ("name-suf", "", {"cand0-suf", "cand1-suf"}, "candidate", {"cand0-suf", "cand1-suf"}),
        ("name-suf", "", {"cand0-suf", "cand1"}, "candidate", {"cand0-suf"}),
        ("name-suf", "", {"cand0", "cand1"}, "candidate", set()),
        # where: name + candidate
        ("name-suf", "", {"cand0-suf", "cand1-suf"}, ("name", "candidate"), {"cand0-suf", "cand1-suf"}),
        ("name-suf", "", {"cand0-suf", "cand1"}, ("name", "candidate"), {"cand0-suf"}),
        ("name", "", {"cand0-suf", "cand1-suf"}, ("name", "candidate"), set()),
        ("name-suf", "", {"cand0", "cand1"}, ("name", "candidate"), set()),
        # where: context
        ("whatever", "context-suf", {"cand0", "cand1"}, "context", {"cand0", "cand1"}),
        ("whatever", "context", {"cand0-suf", "cand1-suf"}, "context", set()),
        # where: name + context
        ("name", "context-suf", {"cand0-suf", "cand1-suf"}, ("name", "context"), set()),
        ("name-suf", "context", {"cand0-suf", "cand1-suf"}, ("name", "context"), set()),
        ("name-suf", "context-suf", {"cand0-suf", "cand1-suf"}, ("name", "context"), {"cand0-suf", "cand1-suf"}),
        ("name-suf", "context-suf", {"cand0-suf", "cand1"}, ("name", "context", "candidate"), {"cand0-suf"}),
    ],
    ids=[
        "where-name-hit",
        "where-name-miss",
        "where-cand-2-hit",
        "where-cand-1-hit",
        "where-cand-miss",
        "where-name/cand-2-hit",
        "where-name/cand-1-hit",
        "where-name/cand-name-miss",
        "where-name/cand-cand-miss",
        "where-context-hit",
        "where-context-miss",
        "where-name/context-miss1",
        "where-name/context-miss2",
        "where-name/context-hit",
        "where-name/context/cand-hit",
    ],
)
def test_require_regex_match(name, context, candidates, where, expected):
    actual = mf.require_regex_match(name, candidates, regex=".*suf$", where=where, context=context)
    assert actual == expected


@pytest.mark.parametrize(
    "name, context, where, candidates, expected",
    [
        # where: name
        ("torque", "", "name", set("abc"), set()),
        ("abc", "", "name", ["more", "torque"], {"more", "torque"}),
        # where: candidate
        ("torque", "", "candidate", set("abc"), set("abc")),
        ("abc", "", "candidate", ["more", "torque"], set()),
        # where: name + candidate
        ("torque", "", ("name", "candidate"), ["more", "torque", "a"], set()),
        ("abc", "", ("name", "candidate"), ["more", "torque", "a"], {"a"}),
        # where: context
        ("", "torque", "context", set("abc"), set()),
        ("", "abc", "context", ["more", "torque"], {"more", "torque"}),
    ],
)
def test_banned_substring(name, context, where, candidates, expected):
    actual = mf.banned_substring(name, candidates=candidates, substrings=KEYWORDS, where=where, context=context)
    assert actual == expected

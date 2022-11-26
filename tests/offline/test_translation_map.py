def test_copy(translation_map):
    c = translation_map.copy()

    assert c.fmt == translation_map.fmt
    assert c.default_fmt == translation_map.default_fmt
    assert c.default_fmt_placeholders == translation_map.default_fmt_placeholders
    assert len(c) == len(translation_map)
    assert all(left == right for left, right in zip(c, translation_map))


def test_props(translation_map):
    assert translation_map.sources == ["title_basics", "name_basics"]
    assert translation_map.names == ["firstTitle", "nconst"]
    assert sorted(translation_map) == sorted(["title_basics", "name_basics", "firstTitle", "nconst"])

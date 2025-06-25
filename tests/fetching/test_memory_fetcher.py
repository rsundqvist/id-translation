from id_translation.fetching import MemoryFetcher
from id_translation.fetching.types import FetchInstruction
from id_translation.offline.types import PlaceholderTranslations


def test_unfiltered(data):
    actual = fetch_translations(data, return_all=True)
    assert actual == PlaceholderTranslations(
        source="humans",
        placeholders=("id", "name", "gender"),
        records=[[1991, "Richard", "Male"], [1999, "Sofia", "Female"]],
        id_pos=0,
    )


def test_filtered(data):
    actual = fetch_translations(data, return_all=False)
    assert actual == PlaceholderTranslations(source="humans", placeholders=("name",), records=(("Sofia",),), id_pos=-1)


def fetch_translations(data, return_all):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher(data, return_all=return_all)
    instr = FetchInstruction(
        "humans",
        placeholders=("name",),
        required=set(),
        ids={1999},
        task_id=-1,
        enable_uuid_heuristics=False,
    )

    return fetcher.fetch_translations(instr)

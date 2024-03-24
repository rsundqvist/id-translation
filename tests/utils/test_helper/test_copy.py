import pytest
from id_translation.exceptions import TooManyFailedTranslationsError

pytestmark = pytest.mark.xfail(strict=True, reason="Not implemented.")


def _test_no_untranslated(get_3_imdb):
    kwargs = {"maximal_untranslated_fraction": 0, "default_fmt_placeholders": None}
    with pytest.raises(TooManyFailedTranslationsError):
        get_3_imdb(translate=kwargs)


def _test_dummy_translations(get_3_imdb):
    assert get_3_imdb(translate={"fmt": "{id}:{name}", "mapper": None, "fetcher": None}) == {
        "name_basics": ["1:name-of-1", "2:name-of-2", "3:name-of-3"],
        "title_basics": ["25509:name-of-25509", "35803:name-of-35803", "38276:name-of-38276"],
    }

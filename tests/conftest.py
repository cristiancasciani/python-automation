import pytest

from ordo.i18n import set_lang


@pytest.fixture(autouse=True)
def english():
    """Tests check English texts unless they switch language themselves."""
    set_lang('en')
    yield
    set_lang('en')

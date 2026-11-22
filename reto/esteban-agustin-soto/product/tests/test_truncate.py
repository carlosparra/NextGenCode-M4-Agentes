"""Pruebas de la función pura ``limit_text`` (sesión 8).

Todo sin red y con datos ficticios.
"""

import pytest

from app.truncate import ELLIPSIS, limit_text


def test_shorter_text_is_left_alone_and_reports_its_length():
    assert limit_text("hello", 10) == ("hello", 5)


def test_text_exactly_at_the_limit_is_left_alone():
    text = "a" * 20
    assert limit_text(text, 20) == (text, 20)


def test_one_character_over_the_limit_is_cut_to_exactly_the_limit():
    text = "abcdefghij" + "k"
    result, original = limit_text(text, 10)
    assert len(result) == 10
    assert result.endswith(ELLIPSIS)
    assert result[:-1] == text[:9]
    assert original == 11


def test_very_long_text_is_cut_to_the_limit():
    text = "x" * 100_000
    result, original = limit_text(text, 1500)
    assert len(result) == 1500
    assert result == "x" * 1499 + ELLIPSIS
    assert original == 100_000


def test_empty_text_stays_empty():
    assert limit_text("", 5) == ("", 0)


def test_limit_of_one_keeps_only_the_ellipsis_when_text_is_longer():
    assert limit_text("ab", 1) == (ELLIPSIS, 2)
    assert limit_text("a" * 50, 1) == (ELLIPSIS, 50)


def test_limit_of_one_keeps_a_single_character_text():
    assert limit_text("a", 1) == ("a", 1)


def test_accents_enie_and_an_existing_ellipsis_are_counted_as_one_character():
    text = f"Año {ELLIPSIS} está así"
    result, original = limit_text(text, 8)
    assert original == len(text)
    assert result == f"Año {ELLIPSIS} e{ELLIPSIS}"
    assert len(result) == 8
    assert result.count(ELLIPSIS) == 2


@pytest.mark.parametrize("limit", [0, -1, -1500])
def test_a_limit_below_one_is_rejected(limit):
    with pytest.raises(ValueError):
        limit_text("text", limit)


def test_the_marker_is_the_single_ellipsis_character_fixed_by_the_spec():
    assert ELLIPSIS == "…"
    assert limit_text("abc", 2) == ("a…", 3)


def test_cutting_an_already_cut_text_changes_nothing():
    once, _ = limit_text("abcdefghijklmnop", 8)
    twice, original = limit_text(once, 8)
    assert twice == once
    assert original == 8

"""Unit tests for app.pii: detection, markers, idempotence and speed.

Only fictitious data is used: the CURP and the email are made up.
"""

import json
import time

import pytest

from conftest import EMPLOYEES
from app.pii import count_pii, mask_text

CURP = "AAAA010101HDFBBB09"
EMAIL = "persona.prueba@example.com"
MAX_SECONDS = 1.0


@pytest.mark.parametrize("curp", [CURP, CURP.lower(), "AEXX991231MNEBCD70"])
def test_valid_curp_is_masked_in_any_case(curp):
    assert mask_text(f"CURP: {curp}") == "CURP: [CURP]"


@pytest.mark.parametrize("text, expected", [
    (f"{CURP} is my data", "[CURP] is my data"),
    (f"My data is {CURP}", "My data is [CURP]"),
    (f"My CURP ({CURP}), thanks.", "My CURP ([CURP]), thanks."),
    (f"{CURP} and {CURP.lower()}", "[CURP] and [CURP]"),
])
def test_curp_is_masked_at_every_position_of_a_text(text, expected):
    assert mask_text(text) == expected


@pytest.mark.parametrize("fake", [
    "AAAA011301HDFBBB09",
    "AAAA010132HDFBBB09",
    "AAAA010101HXXBBB09",
    "AAAA010101ZDFBBB09",
    "ABCD010101HDFBBB09",
    "AAAA010101HDFBAB09",
    "AAAA010101HDFBBB0",
    "AAAA010101 HDFBBB09",
    "AAAA-010101-HDFBBB09",
    "X" + CURP,
    "1" + CURP,
    CURP + "X",
    CURP + "1",
])
def test_text_that_is_not_a_whole_curp_is_left_alone(fake):
    assert mask_text(fake) == fake
    assert count_pii(fake)["curp"] == 0


@pytest.mark.parametrize("address", [
    EMAIL,
    "persona+rh@example.com",
    "persona@mail.rh.example.com.mx",
    "a@b.co",
    "a@b." + "c" * 24,
])
def test_valid_email_is_masked(address):
    assert mask_text(f"Write to {address}, please.") == "Write to [EMAIL], please."


def test_several_emails_in_one_text_are_all_masked():
    text = f"{EMAIL} and persona+x@mail.example.com."
    assert mask_text(text) == "[EMAIL] and [EMAIL]."


@pytest.mark.parametrize("fake", [
    "@juan",
    "write to @juan today",
    "juan@",
    "juan@localhost",
    "juan@example",
    "juan@example.c",
    "a@b." + "c" * 25,
    "no domain here",
])
def test_text_that_is_not_an_email_is_left_alone(fake):
    assert mask_text(fake) == fake
    assert count_pii(fake)["email"] == 0


def test_count_pii_counts_each_kind_without_changing_the_text():
    text = f"{CURP} {CURP.lower()} {EMAIL}"
    assert count_pii(text) == {"curp": 2, "email": 1}
    assert count_pii("nothing to hide") == {"curp": 0, "email": 0}
    assert mask_text(text) == "[CURP] [CURP] [EMAIL]"


def test_masking_twice_changes_nothing():
    once = mask_text(f"{CURP} {EMAIL} and [CURP] [EMAIL]")
    assert once == "[CURP] [EMAIL] and [CURP] [EMAIL]"
    assert mask_text(once) == once
    assert count_pii(once) == {"curp": 0, "email": 0}


def test_directory_data_is_never_a_false_positive():
    data = json.dumps(EMPLOYEES, ensure_ascii=False)
    for text in (data, "EMP-0004", "Jorge Diaz", "Tecnologia", "2022-01-10"):
        assert mask_text(text) == text
        assert count_pii(text) == {"curp": 0, "email": 0}


def test_hostile_text_of_the_maximum_size_is_processed_fast():
    hostile = [
        "a@" * 1000, "." * 2000, "a." * 1000, "A" * 2000, "a" * 1999 + "@",
        "a@b" + "." * 1997, "a" * 1000 + "@" + "b." * 499 + "b", "a@a." * 500,
        "AAAA0101" * 250, (CURP * 112)[:2000], f"{CURP} " * 105,
        "-" * 1000 + "@" + "a" * 999,
    ]
    started = time.perf_counter()
    for text in hostile:
        assert len(text) <= 2000
        mask_text(text)
        count_pii(text)
    assert time.perf_counter() - started < MAX_SECONDS

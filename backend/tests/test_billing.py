"""Логіка пейволу: хто проходить, хто впирається в 402."""
from marko.services.billing import has_access

LIMIT = 30


def test_free_checks_within_limit_pass():
    assert has_access(1, False, LIMIT)
    assert has_access(30, False, LIMIT)


def test_check_over_limit_blocked():
    assert not has_access(31, False, LIMIT)
    assert not has_access(100, False, LIMIT)


def test_full_access_never_blocked():
    assert has_access(1000, True, LIMIT)

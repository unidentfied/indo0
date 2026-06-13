import pytest

from app.services.retry_utils import retry_external, RETRIABLE


def test_retry_external_succeeds_first_try():
    call_count = [0]

    @retry_external(retries=3, backoff_base=0.01, label="test_success")
    def succeed():
        call_count[0] += 1
        return "ok"

    result = succeed()
    assert result == "ok"
    assert call_count[0] == 1


def test_retry_external_retries_on_connection_error():
    call_count = [0]

    @retry_external(retries=3, backoff_base=0.01, label="test_retry")
    def flaky():
        call_count[0] += 1
        if call_count[0] < 2:
            raise ConnectionError("simulated")
        return "ok"

    result = flaky()
    assert result == "ok"
    assert call_count[0] == 2


def test_retry_external_does_not_retry_value_error():
    call_count = [0]

    @retry_external(retries=3, backoff_base=0.01, label="test_no_retry")
    def bad():
        call_count[0] += 1
        raise ValueError("not retriable")

    with pytest.raises(ValueError):
        bad()
    assert call_count[0] == 1


def test_retry_external_fallback():
    @retry_external(retries=2, backoff_base=0.01, label="test_fallback", fallback=lambda *a, **kw: "fallback_value")
    def always_fails():
        raise ConnectionError("always")

    result = always_fails()
    assert result == "fallback_value"

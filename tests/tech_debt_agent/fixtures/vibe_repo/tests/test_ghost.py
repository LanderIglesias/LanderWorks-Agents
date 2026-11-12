from unittest import mock

from app.clean import total_amount, Invoice


def test_no_asserts():
    total_amount(Invoice(100.0, 0.21))


def test_trivial_assert():
    assert True


def test_only_mock_called():
    m = mock.Mock()
    m("x")
    m.assert_called_once()

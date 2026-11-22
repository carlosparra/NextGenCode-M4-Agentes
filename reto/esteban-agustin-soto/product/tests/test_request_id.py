"""Unit tests for the request id validation in app.main."""

import uuid

import pytest


@pytest.mark.parametrize("hostile", ["x" * 129, "bad\tid"])
def test_hostile_request_id_is_replaced_by_a_uuid(make_observed_client, hostile):
    client, stream = make_observed_client()
    response = client.get("/health", headers={"X-Request-ID": hostile})
    returned = response.headers["X-Request-ID"]
    assert returned != hostile
    uuid.UUID(returned)
    assert hostile not in stream.getvalue()

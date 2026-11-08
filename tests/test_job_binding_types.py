"""Public binding annotations describe existing frozen request results only."""

from inspect import unwrap
from typing import get_type_hints

import pytest
from modkit_events.persistence.bindings import FrozenRequest

from modkit_workers.persistence import bindings


@pytest.mark.parametrize("name", ["submit", "read_job", "list_jobs", "acquire"])
def test_public_builders_annotate_the_shared_frozen_request(name):
    function = unwrap(getattr(bindings, name))
    assert get_type_hints(function).get("return") is FrozenRequest


def test_find_annotates_its_comparison_only_request_pair():
    assert get_type_hints(unwrap(bindings.find_jobs))["return"] is bindings.PreparedJobFind
    assert get_type_hints(bindings.PreparedJobFind) == {
        "lookup": FrozenRequest,
        "expected_submission": FrozenRequest,
    }

from __future__ import annotations

import os
import re

import pytest

from .config import ConfigurationError, LiveConfig, load_live_config


@pytest.fixture(scope="session")
def live_config(request: pytest.FixtureRequest) -> LiveConfig:
    # A token exported for normal SDK use must not spend account units on a
    # plain `pytest` run. Match the marker as a whole token, not a substring.
    if "e2e" not in re.split(r"[\s()]+", request.config.getoption("markexpr")):
        pytest.skip("live BQL E2E requires -m e2e")
    try:
        config = load_live_config(os.environ)
    except ConfigurationError as error:
        pytest.fail(str(error), pytrace=False)

    if config is None:
        pytest.skip(
            "live BQL E2E requires BROWSERLESS_TOKEN (and optionally BROWSERLESS_URL)"
        )
    return config

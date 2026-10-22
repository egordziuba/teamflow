"""Optional local integration dependencies; API failures must remain failures."""
import os
from pathlib import Path

import pytest

from teamflow.runtime import find_install, runtime_python


@pytest.fixture(scope='session')
def hermes_install():
    try:
        override = os.environ.get('TEAMFLOW_TEST_HERMES_REPO')
        repo = Path(override).expanduser().resolve() if override is not None else find_install()
        runtime_python(repo)
    except ValueError as error:
        reason = f'Local Hermes integration unavailable: {error}'
        if os.environ.get('TEAMFLOW_REQUIRE_HERMES') == '1':
            pytest.fail(f'{reason} (TEAMFLOW_REQUIRE_HERMES=1)', pytrace=False)
        pytest.skip(reason)
    return repo


@pytest.fixture
def hermes_repo(request, hermes_install):
    """Give unittest integration methods the same validated installation."""
    request.instance.hermes_repo = hermes_install

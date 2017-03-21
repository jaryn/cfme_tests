import requests
import pytest

from cfme.containers.provider import ContainersProvider
from utils import testgen
from utils.version import current_version


pytestmark = [
    pytest.mark.uncollectif(lambda provider: current_version() < "5.6"),
    pytest.mark.usefixtures('setup_provider'),
    pytest.mark.tier(1)]
pytest_generate_tests = testgen.generate([ContainersProvider], scope='function')


def test_basic_metrics(provider):
    """ Basic Metrics availability test
        This test checks that the Metrics service is up
        Curls the hawkular status page and checks if it's up
        """

    client = provider.get_mgmt_system().kubeshift_api
    hm_api = client.routes(namespace="openshift-infra").by_name("hawkular-metrics")["spec"]["host"]
    status_url = 'https://' + hm_api + '/hawkular/metrics/status'
    response = requests.get(status_url, verify=False)
    assert response.json().get("MetricsService") == "STARTED"

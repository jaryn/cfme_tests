# -*- coding: utf-8 -*-
import pytest
from cfme.containers.provider import ContainersProvider
from utils import testgen
from utils.appliance.implementations.ui import navigate_to


pytestmark = [
    pytest.mark.usefixtures('setup_provider'),
    pytest.mark.meta(
        server_roles='+ems_metrics_coordinator +ems_metrics_collector +ems_metrics_processor'),
    pytest.mark.tier(1)]
pytest_generate_tests = testgen.generate([ContainersProvider], scope='function')


def test_plots_presence(provider):
    """ Check whether provider utilisation plots are displayed. """
    utilisation_view = navigate_to(provider, 'Utilization')

    plot_titles = 'CPU (%)', 'Memory (MB)', 'Network I/O(KBps)'
    for title in plot_titles:
        assert utilisation_view.has_plot(title)


# -*- coding: utf-8 -*-
import pytest
from cfme.containers.pod import Pod, list_tbl as list_tbl_pods
from cfme.containers.route import Route, list_tbl as list_tbl_routes
from cfme.containers.project import Project, list_tbl as list_tbl_projects
from cfme.containers.service import Service, list_tbl as list_tbl_services
from utils import testgen
from utils.version import current_version
from utils.appliance.implementations.ui import navigate_to


pytestmark = [
    pytest.mark.uncollectif(
        lambda: current_version() < "5.6"),
    pytest.mark.usefixtures('setup_provider'),
    pytest.mark.tier(1)]
pytest_generate_tests = testgen.generate(
    testgen.container_providers, scope="module")


def _all_names_in_ui_table(navigateable, list_tbl):
    navigate_to(navigateable, 'All')
    return (r.name.text for r in list_tbl.rows())


@pytest.fixture(scope="module")
def pods_names():
    return _all_names_in_ui_table(Pod, list_tbl_pods)


@pytest.fixture(scope="module")
def routes_names():
    return _all_names_in_ui_table(Route, list_tbl_routes)


@pytest.fixture(scope="module")
def projects_names():
    return _all_names_in_ui_table(Project, list_tbl_projects)


@pytest.fixture(scope="module")
def services_names():
    return _all_names_in_ui_table(Service, list_tbl_services)


# CMP-9911
@pytest.mark.parametrize('rel',
                         ['name',
                          'phase',
                          'creation_timestamp',
                          'resource_version',
                          'restart_policy',
                          'dns_policy',
                          'ip_address'
                          ])
def test_pods_properties_rel(provider, pods_names, rel):
    """ Properties table fields tests - Containers Pods' summary page
    This test verifies the fields of the Properties table in Containers Pods'
    details menu
    Steps:
    Containers -- > Containers Pods
    Loop through each Pod object in the table and check validity of
    the fields in the Properties table
    """
    for name in pods_names:
        obj = Pod(name, provider)
        assert getattr(obj.summary.properties, rel).text_value


# CMP-9877
@pytest.mark.parametrize('rel',
                         ['name',
                          'creation_timestamp',
                          'resource_version',
                          'host_name'
                          ])
def test_routes_properties_rel(provider, routes_names, rel):
    """ Properties table fields tests - Containers Routes' summary page
    This test verifies the fields of the Properties table in Containers Routes'
    details menu
    Steps:
    Containers -- > Containers Routes
    Loop through each Route object in the table and check validity of
    the fields in the Properties table
    """
    for name in routes_names:
        obj = Route(name, provider)
        assert getattr(obj.summary.properties, rel).text_value


# CMP-9867
@pytest.mark.parametrize('rel',
                         ['name',
                          'creation_timestamp',
                          'resource_version'
                          ])
def test_projects_properties_rel(provider, projects_names, rel):
    """ Properties table fields tests - Containers Projects' summary page
    This test verifies the fields of the Properties table in Containers Projects'
    details menu
    Steps:
    Containers -- > Containers Projects
    Loop through each Project object in the table and check validity of
    the fields in the Properties table
    """
    for name in projects_names:
        obj = Project(name, provider)
        assert getattr(obj.summary.properties, rel).text_value


# CMP-9884
@pytest.mark.parametrize('rel',
                         ['name',
                          'creation_timestamp',
                          'resource_version',
                          'session_affinity',
                          'type',
                          'portal_ip'
                          ])
def test_services_properties_rel(provider, services_names, rel):
    """ Properties table fields tests - Containers Services' summary page
    This test verifies the fields of the Properties table in Containers Services'
    details menu
    Steps:
    Containers -- > Containers Services
    Loop through each Service object in the table and check validity of
    the fields in the Properties table
    """
    for name in services_names:
        obj = Service(name, provider)
        assert getattr(obj.summary.properties, rel).text_value

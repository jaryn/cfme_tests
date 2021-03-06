# -*- coding: utf-8 -*-
import fauxfactory
import pytest

from cfme.common.vm import VM
from cfme.web_ui import InfoBlock, toolbar, jstimelines
from cfme.exceptions import ToolbarOptionGreyedOrUnavailable
from utils import testgen
from utils import version
from utils.log import logger
from utils.wait import wait_for

pytestmark = [pytest.mark.ignore_stream("upstream")]


@pytest.fixture(scope="module")
def delete_fx_provider_event(db, provider):
    logger.debug("Deleting timeline events for provider name {}".format(provider.name))
    ems = db['ext_management_systems']
    ems_events_table_name = version.pick({version.LOWEST: 'ems_events', '5.5': 'event_streams'})
    ems_events = db[ems_events_table_name]
    with db.transaction:
        providers = (
            db.session.query(ems_events.id)
            .join(ems, ems_events.ems_id == ems.id)
            .filter(ems.name == provider.name)
        )
        db.session.query(ems_events).filter(ems_events.id.in_(providers.subquery())).delete(False)


def pytest_generate_tests(metafunc):
    argnames, argvalues, idlist = testgen.provider_by_type(metafunc, ['virtualcenter', 'rhevm'])
    testgen.parametrize(metafunc, argnames, argvalues, ids=idlist, scope="module")


@pytest.fixture(scope="module")
def vm_name():
    # We have to use "tt" here to avoid name truncating in the timelines view
    return "test_tt_" + fauxfactory.gen_alphanumeric(length=4)


@pytest.fixture(scope="module")
def test_vm(request, provider, vm_name, setup_provider_modscope):
    """Fixture to provision appliance to the provider being tested if necessary"""
    pytest.sel.force_navigate('infrastructure_providers')
    vm = VM.factory(vm_name, provider)

    request.addfinalizer(vm.delete_from_provider)

    if not provider.mgmt.does_vm_exist(vm_name):
        vm.create_on_provider(find_in_cfme=True, allow_skip="default")
    return vm


@pytest.fixture(scope="module")
def gen_events(delete_fx_provider_event, provider, test_vm):
    logger.debug('Starting, stopping VM')
    mgmt = provider.mgmt
    mgmt.stop_vm(test_vm.name)
    mgmt.start_vm(test_vm.name)


def count_events(vm_name, nav_step):
    try:
        nav_step()
    except ToolbarOptionGreyedOrUnavailable:
        return 0
    events = []
    for event in jstimelines.events():
        data = event.block_info()
        if vm_name in data.values():
            events.append(event)
            if len(events) > 0:
                return len(events)
    return 0


@pytest.mark.meta(blockers=[1264183, 1281746])
def test_provider_event(provider, gen_events, test_vm):
    """Tests provider event on timelines

    Metadata:
        test_flag: timelines, provision
    """
    def nav_step():
        pytest.sel.force_navigate('infrastructure_provider',
                                  context={'provider': provider})
        toolbar.select('Monitoring', 'Timelines')
    wait_for(count_events, [test_vm.name, nav_step], timeout=60, fail_condition=0,
             message="events to appear")


@pytest.mark.meta(blockers=[1281746])
def test_host_event(provider, gen_events, test_vm):
    """Tests host event on timelines

    Metadata:
        test_flag: timelines, provision
    """
    def nav_step():
        test_vm.load_details()
        pytest.sel.click(InfoBlock.element('Relationships', 'Host'))
        toolbar.select('Monitoring', 'Timelines')
    wait_for(count_events, [test_vm.name, nav_step], timeout=60, fail_condition=0,
             message="events to appear")


@pytest.mark.meta(blockers=[1281746])
def test_vm_event(provider, gen_events, test_vm):
    """Tests vm event on timelines

    Metadata:
        test_flag: timelines, provision
    """
    def nav_step():
        test_vm.load_details()
        toolbar.select('Monitoring', 'Timelines')
    wait_for(count_events, [test_vm.name, nav_step], timeout=60, fail_condition=0,
             message="events to appear")


@pytest.mark.meta(blockers=[1281746])
def test_cluster_event(provider, gen_events, test_vm):
    """Tests cluster event on timelines

    Metadata:
        test_flag: timelines, provision
    """
    def nav_step():
        test_vm.load_details()
        pytest.sel.click(InfoBlock.element('Relationships', 'Cluster'))
        toolbar.select('Monitoring', 'Timelines')
    wait_for(count_events, [test_vm.name, nav_step], timeout=60, fail_condition=0,
             message="events to appear")

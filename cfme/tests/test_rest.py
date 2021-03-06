# -*- coding: utf-8 -*-
"""This module contains REST API specific tests."""
import datetime
import fauxfactory
import pytest

from cfme import Credential
from cfme.automate.service_dialogs import ServiceDialog
from cfme.configure.access_control import User, Group
from cfme.configure.configuration import server_roles_disabled
from cfme.login import login
from cfme.services.catalogs.catalog_item import CatalogItem
from cfme.services.catalogs.service_catalogs import ServiceCatalogs
from cfme.services import requests
from utils.providers import setup_a_provider as _setup_a_provider
from utils.version import current_version
from utils.virtual_machines import deploy_template
from utils.wait import wait_for
from utils import error, mgmt_system, testgen, conf, version


pytest_generate_tests = testgen.generate(
    testgen.provider_by_type,
    ['virtualcenter', 'rhevm'],
    "small_template",
    scope="module"
)

pytestmark = [pytest.mark.ignore_stream("5.2")]


@pytest.fixture(scope="module")
def a_provider():
    return _setup_a_provider("infra")


@pytest.fixture(scope="module")
def provision_data(
        rest_api_modscope, provider, small_template):
    templates = rest_api_modscope.collections.templates.find_by(name=small_template)
    for template in templates:
        if template.ems.name == provider.data["name"]:
            guid = template.guid
            break
    else:
        raise Exception("No such template {} on provider!".format(small_template))
    result = {
        "version": "1.1",
        "template_fields": {
            "guid": guid
        },
        "vm_fields": {
            "number_of_cpus": 1,
            "vm_name": "test_rest_prov_{}".format(fauxfactory.gen_alphanumeric()),
            "vm_memory": "2048",
            "vlan": provider.data["provisioning"]["vlan"],
        },
        "requester": {
            "user_name": "admin",
            "owner_first_name": "John",
            "owner_last_name": "Doe",
            "owner_email": "jdoe@sample.com",
            "auto_approve": True
        },
        "tags": {
            "network_location": "Internal",
            "cc": "001"
        },
        "additional_values": {
            "request_id": "1001"
        },
        "ems_custom_attributes": {},
        "miq_custom_attributes": {}
    }
    if isinstance(provider.mgmt, mgmt_system.RHEVMSystem):
        result["vm_fields"]["provision_type"] = "native_clone"
    return result


@pytest.fixture(scope='function')
def service_catalogs(request, rest_api):
    name = fauxfactory.gen_alphanumeric()
    rest_api.collections.service_catalogs.action.add(
        name=name,
        description="description_{}".format(name),
        service_templates=[]
    )[0]
    wait_for(
        lambda: rest_api.collections.service_catalogs.find_by(name=name),
        num_sec=180,
        delay=10,
    )

    scls_data = [{
        "name": "name_{}_{}".format(name, index),
        "description": "description_{}_{}".format(name, index),
        "service_templates": []
    } for index in range(1, 5)]
    scls = rest_api.collections.service_catalogs.action.add(*scls_data)

    @request.addfinalizer
    def _finished():
        scls = [_ for _ in rest_api.collections.service_catalogs]
        if len(scls) != 0:
            rest_api.collections.service_catalogs.action.delete(*scls)

    return scls


@pytest.mark.usefixtures("logged_in")
@pytest.fixture(scope='function')
def dialog():
    dialog = "dialog_{}".format(fauxfactory.gen_alphanumeric())
    element_data = dict(
        ele_label="ele_{}".format(fauxfactory.gen_alphanumeric()),
        ele_name=fauxfactory.gen_alphanumeric(),
        ele_desc="my ele desc",
        choose_type="Text Box",
        default_text_box="default value"
    )
    service_dialog = ServiceDialog(
        label=dialog,
        description="my dialog",
        submit=True,
        cancel=True,
        tab_label="tab_{}".format(fauxfactory.gen_alphanumeric()),
        tab_desc="my tab desc",
        box_label="box_{}".format(fauxfactory.gen_alphanumeric()),
        box_desc="my box desc")
    service_dialog.create(element_data)
    return service_dialog


@pytest.mark.usefixtures("logged_in")
@pytest.fixture(scope='function')
def user():
    user = User(credential=Credential(principal=fauxfactory.gen_alphanumeric(),
        secret=fauxfactory.gen_alphanumeric()), name=fauxfactory.gen_alphanumeric(),
        group=Group(description='EvmGroup-super_administrator'))
    user.create()
    return user


@pytest.mark.usefixtures("logged_in")
@pytest.fixture(scope='function')
def service_templates(request, rest_api, dialog):
    catalog_items = []
    for index in range(1, 5):
        catalog_items.append(
            CatalogItem(
                item_type="Generic",
                name="item_{}_{}".format(index, fauxfactory.gen_alphanumeric()),
                description="my catalog", display_in=True,
                dialog=dialog.label)
        )

    for catalog_item in catalog_items:
        catalog_item.create()

    try:
        s_tpls = [_ for _ in rest_api.collections.service_templates]
        s_tpls[0]
    except IndexError:
        pytest.skip("There is no service template to be taken")

    @request.addfinalizer
    def _finished():
        s_tpls = [_ for _ in rest_api.collections.service_templates]
        if len(s_tpls) != 0:
            rest_api.collections.service_templates.action.delete(*s_tpls)

    return s_tpls


@pytest.mark.usefixtures("setup_provider")
@pytest.mark.usefixtures("logged_in")
@pytest.fixture(scope='function')
def services(request, a_provider, rest_api, dialog, service_catalogs):
    """
    The attempt to add the service entities via web
    """
    template, host, datastore, iso_file, vlan, catalog_item_type = map(a_provider.data.get(
        "provisioning").get,
        ('template', 'host', 'datastore', 'iso_file', 'vlan', 'catalog_item_type'))

    provisioning_data = {
        'vm_name': 'test_rest_{}'.format(fauxfactory.gen_alphanumeric()),
        'host_name': {'name': [host]},
        'datastore_name': {'name': [datastore]}
    }

    if a_provider.type == 'rhevm':
        provisioning_data['provision_type'] = 'Native Clone'
        provisioning_data['vlan'] = vlan
        catalog_item_type = version.pick({
            version.LATEST: "RHEV",
            '5.3': "RHEV",
            '5.2': "Redhat"
        })
    elif a_provider.type == 'virtualcenter':
        provisioning_data['provision_type'] = 'VMware'
    catalog = service_catalogs[0].name
    item_name = fauxfactory.gen_alphanumeric()
    catalog_item = CatalogItem(item_type=catalog_item_type, name=item_name,
                               description="my catalog", display_in=True,
                               catalog=catalog,
                               dialog=dialog.label,
                               catalog_name=template,
                               provider=a_provider.name,
                               prov_data=provisioning_data)

    catalog_item.create()
    service_catalogs = ServiceCatalogs("service_name")
    service_catalogs.order(catalog_item.catalog, catalog_item)
    row_description = catalog_item.name
    cells = {'Description': row_description}
    row, __ = wait_for(requests.wait_for_request, [cells, True],
        fail_func=requests.reload, num_sec=2000, delay=20)
    assert row.last_message.text == 'Request complete'
    try:
        services = [_ for _ in rest_api.collections.services]
        services[0]
    except IndexError:
        pytest.skip("There is no service to be taken")

    @request.addfinalizer
    def _finished():
        services = [_ for _ in rest_api.collections.services]
        if len(services) != 0:
            rest_api.collections.services.action.delete(*services)

    return services


@pytest.fixture(scope='function')
def automation_requests_data():
    return [{
        "uri_parts": {
            "namespace": "System",
            "class": "Request",
            "instance": "InspectME",
            "message": "create",
        },
        "parameters": {
            "vm_name": "test_rest_{}".format(fauxfactory.gen_alphanumeric()),
            "vm_memory": 4096,
            "memory_limit": 16384,
        },
        "requester": {
            "auto_approve": True
        }
    } for index in range(1, 5)]


@pytest.fixture(scope='function')
def roles(request, rest_api):
    if "create" not in rest_api.collections.roles.action.all:
        pytest.skip("Create roles action is not implemented in this version")

    roles_data = [{
        "name": "role_name_{}".format(fauxfactory.gen_alphanumeric())
    } for index in range(1, 5)]

    roles = rest_api.collections.roles.action.create(*roles_data)
    for role in roles:
        wait_for(
            lambda: rest_api.collections.roles.find_by(name=role.name),
            num_sec=180,
            delay=10,
        )

    @request.addfinalizer
    def _finished():
        ids = [r.id for r in roles]
        delete_roles = [r for r in rest_api.collections.roles if r.id in ids]
        if len(delete_roles) != 0:
            rest_api.collections.roles.action.delete(*delete_roles)

    return roles


@pytest.fixture(scope='function')
def categories(request, rest_api):
    if "create" not in rest_api.collections.categories.action.all:
        pytest.skip("Create categories action is not implemented in this version")
    ctg_data = [{
        'name': 'test_category_{}_{}'.format(fauxfactory.gen_alphanumeric().lower(), _index),
        'description': 'test_category_{}_{}'.format(fauxfactory.gen_alphanumeric().lower(), _index)
    } for _index in range(0, 5)]
    ctgs = rest_api.collections.categories.action.create(*ctg_data)
    for ctg in ctgs:
        wait_for(
            lambda: rest_api.collections.categories.find_by(description=ctg.description),
            num_sec=180,
            delay=10,
        )

    @request.addfinalizer
    def _finished():
        ids = [ctg.id for ctg in ctgs]
        delete_ctgs = [ctg for ctg in rest_api.collections.categories
            if ctg.id in ids]
        if len(delete_ctgs) != 0:
            rest_api.collections.categories.action.delete(*delete_ctgs)

    return ctgs


# Here also available the ability to create multiple provision request, but used the save
# href and method, so it doesn't make any sense actually
@pytest.mark.meta(server_roles="+automate")
@pytest.mark.usefixtures("setup_provider")
def test_provision(request, provision_data, provider, rest_api):
    """Tests provision via REST API.
    Prerequisities:
        * Have a provider set up with templates suitable for provisioning.
    Steps:
        * POST /api/provision_requests (method ``create``) the JSON with provisioning data. The
            request is returned.
        * Query the request by its id until the state turns to ``finished`` or ``provisioned``.
    Metadata:
        test_flag: rest, provision
    """

    vm_name = provision_data["vm_fields"]["vm_name"]
    request.addfinalizer(
        lambda: provider.mgmt.delete_vm(vm_name) if provider.mgmt.does_vm_exist(vm_name) else None)
    request = rest_api.collections.provision_requests.action.create(**provision_data)[0]

    def _finished():
        request.reload()
        if request.status.lower() in {"error"}:
            pytest.fail("Error when provisioning: `{}`".format(request.message))
        return request.request_state.lower() in {"finished", "provisioned"}

    wait_for(_finished, num_sec=600, delay=5, message="REST provisioning finishes")
    assert provider.mgmt.does_vm_exist(vm_name), "The VM {} does not exist!".format(vm_name)


def test_delete_service_catalog(rest_api, service_catalogs):
    scl = service_catalogs[0]
    scl.action.delete()
    with error.expected("ActiveRecord::RecordNotFound"):
        scl.action.delete()


def test_delete_service_catalogs(rest_api, service_catalogs):
    rest_api.collections.service_catalogs.action.delete(*service_catalogs)
    with error.expected("ActiveRecord::RecordNotFound"):
        rest_api.collections.service_catalogs.action.delete(*service_catalogs)


def test_edit_service_catalog(rest_api, service_catalogs):
    """Tests editing a service catalog.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/service_catalogs/<id>/ (method ``edit``) with the ``name``
        * Check if the service_catalog with ``new_name`` exists
    Metadata:
        test_flag: rest
    """
    ctl = service_catalogs[0]
    new_name = fauxfactory.gen_alphanumeric()
    ctl.action.edit(name=new_name)
    wait_for(
        lambda: rest_api.collections.service_catalogs.find_by(name=new_name),
        num_sec=180,
        delay=10,
    )


def test_edit_multiple_service_catalogs(rest_api, service_catalogs):
    """Tests editing multiple service catalogs at time.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/service_catalogs (method ``edit``) with the list of dictionaries used to edit
        * Check if the service_catalogs with ``new_name`` each exist
    Metadata:
        test_flag: rest
    """

    new_names = []
    scls_data_edited = []
    for scl in service_catalogs:
        new_name = fauxfactory.gen_alphanumeric()
        new_names.append(new_name)
        scls_data_edited.append({
            "href": scl.href,
            "name": new_name,
        })
    rest_api.collections.service_catalogs.action.edit(*scls_data_edited)
    for new_name in new_names:
        wait_for(
            lambda: rest_api.collections.service_catalogs.find_by(name=new_name),
            num_sec=180,
            delay=10,
        )


def test_edit_service_template(rest_api, service_templates):
    """Tests cediting a service template.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/service_templates (method ``edit``) with the ``name``
        * Check if the service_template with ``new_name`` exists
    Metadata:
        test_flag: rest
    """
    scl = rest_api.collections.service_templates[0]
    new_name = fauxfactory.gen_alphanumeric()
    scl.action.edit(name=new_name)
    wait_for(
        lambda: rest_api.collections.service_catalogs.find_by(name=new_name),
        num_sec=180,
        delay=10,
    )


def test_delete_service_templates(rest_api, service_templates):
    rest_api.collections.service_templates.action.delete(*service_templates)
    with error.expected("ActiveRecord::RecordNotFound"):
        rest_api.collections.service_templates.action.delete(*service_templates)


def test_delete_service_template(rest_api, service_templates):
    s_tpl = rest_api.collections.service_templates[0]
    s_tpl.action.delete()
    with error.expected("ActiveRecord::RecordNotFound"):
        s_tpl.action.delete()


# Didn't test properly
@pytest.mark.uncollectif(True)
def test_assign_unassign_service_template_to_service_catalog(rest_api,
        service_catalogs, service_templates):
    """Tests assigning and unassigning the service templates to service catalog.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/service_catalogs/<id> (method ``assign``) with the list of dictionaries
            service templates list
        * Check if the service_templates were assigned to the service catalog
        * POST /api/service_catalogs/<id> (method ``unassign``) with the list of dictionaries
            service templates list
        * Check if the service_templates were unassigned to the service catalog
    Metadata:
        test_flag: rest
    """

    scl = service_catalogs[0]
    scl.reload()
    scl.action.assign(*service_templates)
    assert len(scl.service_templates) == len(service_templates)
    scl.reload()
    scl.action.unassign(*service_templates)
    assert len(scl.service_templates) == 0


def test_edit_multiple_service_templates(rest_api, service_templates):
    """Tests editing multiple service catalogs at time.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/service_templates (method ``edit``) with the list of dictionaries used to edit
        * Check if the service_templates with ``new_name`` each exists
    Metadata:
        test_flag: rest
    """
    new_names = []
    service_tpls_data_edited = []
    for tpl in service_templates:
        new_name = fauxfactory.gen_alphanumeric()
        new_names.append(new_name)
        service_tpls_data_edited.append({
            "href": tpl.href,
            "name": new_name,
        })
    rest_api.collections.service_templates.action.edit(*service_tpls_data_edited)
    for new_name in new_names:
        wait_for(
            lambda: rest_api.collections.service_templates.find_by(name=new_name),
            num_sec=180,
            delay=10,
        )


def test_edit_service(rest_api, services):
    """Tests editing a service.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/services (method ``edit``) with the ``name``
        * Check if the service with ``new_name`` exists
    Metadata:
        test_flag: rest
    """
    ser = services[0]
    new_name = fauxfactory.gen_alphanumeric()
    ser.action.edit(name=new_name)
    wait_for(
        lambda: rest_api.collections.services.find_by(name=new_name),
        num_sec=180,
        delay=10,
    )


def test_edit_multiple_services(rest_api, services):
    """Tests editing multiple service catalogs at time.
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/services (method ``edit``) with the list of dictionaries used to edit
        * Check if the services with ``new_name`` each exists
    Metadata:
        test_flag: rest
    """
    new_names = []
    services_data_edited = []
    for ser in services:
        new_name = fauxfactory.gen_alphanumeric()
        new_names.append(new_name)
        services_data_edited.append({
            "href": ser.href,
            "name": new_name,
        })
    rest_api.collections.services.action.edit(*services_data_edited)
    for new_name in new_names:
        wait_for(
            lambda: rest_api.collections.service_templates.find_by(name=new_name),
            num_sec=180,
            delay=10,
        )


def test_delete_service(rest_api, services):
    service = rest_api.collections.services[0]
    service.action.delete()
    with error.expected("ActiveRecord::RecordNotFound"):
        service.action.delete()


def test_delete_services(rest_api, services):
    rest_api.collections.services.action.delete(*services)
    with error.expected("ActiveRecord::RecordNotFound"):
        rest_api.collections.services.action.delete(*services)


@pytest.mark.ignore_stream("5.3")
def test_retire_service_now(rest_api, services):
    """Test retiring a service
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * Retrieve list of entities using GET /api/services , pick the first one
        * POST /api/service/<id> (method ``retire``)
    Metadata:
        test_flag: rest
    """
    assert "retire" in rest_api.collections.services.action.all
    retire_service = services[0]
    retire_service.action.retire()
    wait_for(
        lambda: not rest_api.collections.services.find_by(name=retire_service.name),
        num_sec=600,
        delay=10,
    )


@pytest.mark.ignore_stream("5.3")
def test_retire_service_future(rest_api, services):
    """Test retiring a service
    Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * Retrieve list of entities using GET /api/services , pick the first one
        * POST /api/service/<id> (method ``retire``) with the ``retire_date``
    Metadata:
        test_flag: rest
    """
    assert "retire" in rest_api.collections.services.action.all

    retire_service = services[0]
    date = (datetime.datetime.now() + datetime.timedelta(days=5)).strftime('%m/%d/%y')
    future = {
        "date": date,
        "warn": "4",
    }
    date_before = retire_service.updated_at
    retire_service.action.retire(future)

    def _finished():
        retire_service.reload()
        if retire_service.updated_at > date_before:
                return True
        return False

    wait_for(_finished, num_sec=600, delay=5, message="REST automation_request finishes")


def test_provider_refresh(request, a_provider, rest_api):
    """Test checking that refresh invoked from the REST API works.
    It provisions a VM when the Provider inventory functionality is disabled, then the functionality
    is enabled and we wait for refresh to finish by checking the field in provider and then we check
    whether the VM appeared in the provider.
    Prerequisities:
        * A provider that is set up, with templates suitable for provisioning.
    Steps:
        * Disable the ``ems_inventory`` and ``ems_operations`` roles
        * Provision a VM
        * Store old refresh date from the provider
        * Initiate refresh
        * Wait until the refresh date updates
        * The VM should appear soon.
    Metadata:
        test_flag: rest
    """
    if "refresh" not in rest_api.collections.providers.action.all:
        pytest.skip("Refresh action is not implemented in this version")
    provider_rest = rest_api.collections.providers.find_by(name=a_provider.name)[0]
    with server_roles_disabled("ems_inventory", "ems_operations"):
        vm_name = deploy_template(
            a_provider.key,
            "test_rest_prov_refresh_{}".format(fauxfactory.gen_alphanumeric(length=4)))
        request.addfinalizer(lambda: a_provider.mgmt.delete_vm(vm_name))
    provider_rest.reload()
    old_refresh_dt = provider_rest.last_refresh_date
    assert provider_rest.action.refresh()["success"], "Refresh was unsuccessful"
    wait_for(
        lambda: provider_rest.last_refresh_date,
        fail_func=provider_rest.reload,
        fail_condition=lambda refresh_date: refresh_date == old_refresh_dt,
        num_sec=720,
        delay=5,
    )
    # We suppose that thanks to the random string, there will be only one such VM
    wait_for(
        lambda: len(rest_api.collections.vms.find_by(name=vm_name)),
        fail_condition=lambda l: l == 0,
        num_sec=180,
        delay=10,
    )
    vms = rest_api.collections.vms.find_by(name=vm_name)
    if "delete" in vms[0].action.all:
        vms[0].action.delete()


@pytest.mark.ignore_stream("5.3")
def test_provider_edit(request, a_provider, rest_api):
    """Test editing a provider using REST API.
    Prerequisities:
        * A provider that is set up. Can be a dummy one.
    Steps:
        * Retrieve list of providers using GET /api/providers , pick the first one
        * POST /api/providers/<id> (method ``edit``) -> {"name": <random name>}
        * Query the provider again. The name should be set.
    Metadata:
        test_flag: rest
    """
    if "edit" not in rest_api.collections.providers.action.all:
        pytest.skip("Refresh action is not implemented in this version")
    provider_rest = rest_api.collections.providers[0]
    new_name = fauxfactory.gen_alphanumeric()
    old_name = provider_rest.name
    request.addfinalizer(lambda: provider_rest.action.edit(name=old_name))
    provider_rest.action.edit(name=new_name)
    provider_rest.reload()
    assert provider_rest.name == new_name


@pytest.mark.parametrize(
    "from_detail", [True, False],
    ids=["delete_from_detail", "delete_from_collection"])
@pytest.mark.ignore_stream("5.3")
def test_provider_crud(request, rest_api, from_detail):
    """Test the CRUD on provider using REST API.
    Steps:
        * POST /api/providers (method ``create``) <- {"hostname":..., "name":..., "type":
            "EmsVmware"}
        * Remember the provider ID.
        * Delete it either way:
            * DELETE /api/providers/<id>
            * POST /api/providers (method ``delete``) <- list of dicts containing hrefs to the
                providers, in this case just list with one dict.
    Metadata:
        test_flag: rest
    """
    if "create" not in rest_api.collections.providers.action.all:
        pytest.skip("Create action is not implemented in this version")

    if current_version() < "5.5":
        provider_type = "EmsVmware"
    else:
        provider_type = "ManageIQ::Providers::Vmware::InfraManager"
    provider = rest_api.collections.providers.action.create(
        hostname=fauxfactory.gen_alphanumeric(),
        name=fauxfactory.gen_alphanumeric(),
        type=provider_type,
    )[0]
    if from_detail:
        provider.action.delete()
        provider.wait_not_exists(num_sec=30, delay=0.5)
    else:
        rest_api.collections.providers.action.delete(provider)
        provider.wait_not_exists(num_sec=30, delay=0.5)


@pytest.fixture(scope="module")
def vm(request, a_provider, rest_api):
    if "refresh" not in rest_api.collections.providers.action.all:
        pytest.skip("Refresh action is not implemented in this version")
    provider_rest = rest_api.collections.providers.find_by(name=a_provider.name)[0]
    vm_name = deploy_template(
        a_provider.key,
        "test_rest_vm_{}".format(fauxfactory.gen_alphanumeric(length=4)))
    request.addfinalizer(lambda: a_provider.mgmt.delete_vm(vm_name))
    provider_rest.action.refresh()
    wait_for(
        lambda: len(rest_api.collections.vms.find_by(name=vm_name)) > 0,
        num_sec=600, delay=5)
    return vm_name


@pytest.mark.parametrize(
    "from_detail", [True, False],
    ids=["from_detail", "from_collection"])
@pytest.mark.ignore_stream("5.3")
def test_set_vm_owner(request, rest_api, vm, from_detail):
    """Test whether set_owner action from the REST API works.
    Prerequisities:
        * A VM
    Steps:
        * Find a VM id using REST
        * Call either:
            * POST /api/vms/<id> (method ``set_owner``) <- {"owner": "owner username"}
            * POST /api/vms (method ``set_owner``) <- {"owner": "owner username",
                "resources": [{"href": ...}]}
        * Query the VM again
        * Assert it has the attribute ``evm_owner`` as we set it.
    Metadata:
        test_flag: rest
    """
    if "set_owner" not in rest_api.collections.vms.action.all:
        pytest.skip("Set owner action is not implemented in this version")
    rest_vm = rest_api.collections.vms.find_by(name=vm)[0]
    if from_detail:
        assert rest_vm.action.set_owner(owner="admin")["success"], "Could not set owner"
    else:
        assert (
            len(rest_api.collections.vms.action.set_owner(rest_vm, owner="admin")) > 0,
            "Could not set owner")
    rest_vm.reload()
    assert hasattr(rest_vm, "evm_owner")
    assert rest_vm.evm_owner.userid == "admin"


@pytest.mark.parametrize(
    "from_detail", [True, False],
    ids=["from_detail", "from_collection"])
@pytest.mark.ignore_stream("5.3")
def test_vm_add_lifecycle_event(request, rest_api, vm, from_detail, db):
    """Test that checks whether adding a lifecycle event using the REST API works.
    Prerequisities:
        * A VM
    Steps:
        * Find the VM's id
        * Prepare the lifecycle event data (``status``, ``message``, ``event``)
        * Call either:
            * POST /api/vms/<id> (method ``add_lifecycle_event``) <- the lifecycle data
            * POST /api/vms (method ``add_lifecycle_event``) <- the lifecycle data + resources field
                specifying list of dicts containing hrefs to the VMs, in this case only one.
        * Verify that appliance's database contains such entries in table ``lifecycle_events``
    Metadata:
        test_flag: rest
    """
    if "add_lifecycle_event" not in rest_api.collections.vms.action.all:
        pytest.skip("add_lifecycle_event action is not implemented in this version")
    rest_vm = rest_api.collections.vms.find_by(name=vm)[0]
    event = dict(
        status=fauxfactory.gen_alphanumeric(),
        message=fauxfactory.gen_alphanumeric(),
        event=fauxfactory.gen_alphanumeric(),
    )
    if from_detail:
        assert rest_vm.action.add_lifecycle_event(**event)["success"], "Could not add event"
    else:
        assert (
            len(rest_api.collections.vms.action.add_lifecycle_event(rest_vm, **event)) > 0,
            "Could not add event")
    # DB check
    lifecycle_events = db["lifecycle_events"]
    assert len(list(db.session.query(lifecycle_events).filter(
        lifecycle_events.message == event["message"],
        lifecycle_events.status == event["status"],
        lifecycle_events.event == event["event"],
    ))) == 1, "Could not find the lifecycle event in the database"


@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_automation_requests(request, rest_api, automation_requests_data, multiple):
    """Test adding the automation request
     Prerequisities:
        * An appliance with ``/api`` available.
    Steps:
        * POST /api/automation_request - (method ``create``) add request
        * Retrieve list of entities using GET /api/automation_request and find just added request
    Metadata:
        test_flag: rest, requests
    """

    if "automation_requests" not in rest_api.collections:
        pytest.skip("automation request collection is not implemented in this version")

    if multiple:
        requests = rest_api.collections.automation_requests.action.create(*automation_requests_data)
    else:
        requests = rest_api.collections.automation_requests.action.create(
            automation_requests_data[0])

    def _finished():
        for request in requests:
            request.reload()
            if request.status.lower() not in {"error"}:
                return False
        return True

    wait_for(_finished, num_sec=600, delay=5, message="REST automation_request finishes")


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_edit_categories(rest_api, categories, multiple):
    if "edit" not in rest_api.collections.categories.action.all:
        pytest.skip("Edit categories action is not implemented in this version")

    if multiple:
        new_names = []
        ctgs_data_edited = []
        for ctg in categories:
            new_name = fauxfactory.gen_alphanumeric().lower()
            new_names.append(new_name)
            ctg.reload()
            ctgs_data_edited.append({
                "href": ctg.href,
                "description": "test_category_{}".format(new_name),
            })
        rest_api.collections.categories.action.edit(*ctgs_data_edited)
        for new_name in new_names:
            wait_for(
                lambda: rest_api.collections.categories.find_by(description=new_name),
                num_sec=180,
                delay=10,
            )
    else:
        ctg = rest_api.collections.categories.find_by(description=categories[0].description)[0]
        new_name = 'test_category_{}'.format(fauxfactory.gen_alphanumeric().lower())
        ctg.action.edit(description=new_name)
        wait_for(
            lambda: rest_api.collections.categories.find_by(description=new_name),
            num_sec=180,
            delay=10,
        )


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_delete_categories(rest_api, categories, multiple):
    if "delete" not in rest_api.collections.categories.action.all:
        pytest.skip("Delete categories action is not implemented in this version")

    if multiple:
        rest_api.collections.categories.action.delete(*categories)
        with error.expected("ActiveRecord::RecordNotFound"):
            rest_api.collections.categories.action.delete(*categories)
    else:
        ctg = categories[0]
        ctg.action.delete()
        with error.expected("ActiveRecord::RecordNotFound"):
            ctg.action.delete()


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_edit_roles(rest_api, roles, multiple):
    if "edit" not in rest_api.collections.roles.action.all:
        pytest.skip("Edit roles action is not implemented in this version")

    if multiple:
        new_names = []
        roles_data_edited = []
        for role in roles:
            new_name = fauxfactory.gen_alphanumeric()
            new_names.append(new_name)
            role.reload()
            roles_data_edited.append({
                "href": role.href,
                "name": "role_name_{}".format(new_name),
            })
        rest_api.collections.roles.action.edit(*roles_data_edited)
        for new_name in new_names:
            wait_for(
                lambda: rest_api.collections.roles.find_by(name=new_name),
                num_sec=180,
                delay=10,
            )
    else:
        role = rest_api.collections.roles.find_by(name=roles[0].name)[0]
        new_name = 'role_name_{}'.format(fauxfactory.gen_alphanumeric())
        role.action.edit(name=new_name)
        wait_for(
            lambda: rest_api.collections.roles.find_by(name=new_name),
            num_sec=180,
            delay=10,
        )


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
def test_delete_roles(rest_api, roles):
    if "delete" not in rest_api.collections.roles.action.all:
        pytest.skip("Delete roles action is not implemented in this version")

    rest_api.collections.roles.action.delete(*roles)
    with error.expected("ActiveRecord::RecordNotFound"):
        rest_api.collections.roles.action.delete(*roles)


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
def test_add_delete_role(rest_api):
    if "add" not in rest_api.collections.roles.action.all:
        pytest.skip("Add roles action is not implemented in this version")

    role_data = {"name": "role_name_{}".format(format(fauxfactory.gen_alphanumeric()))}
    role = rest_api.collections.roles.action.add(role_data)[0]
    wait_for(
        lambda: rest_api.collections.roles.find_by(name=role.name),
        num_sec=180,
        delay=10,
    )
    role.action.delete()
    with error.expected("ActiveRecord::RecordNotFound"):
        role.action.delete()


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
def test_edit_user_password(rest_api, user):
    if "edit" not in rest_api.collections.users.action.all:
        pytest.skip("Edit action for users is not implemented in this version")
    try:
        for cur_user in rest_api.collections.users:
            if cur_user.userid != conf.credentials['default']['username']:
                rest_user = cur_user
                break
    except:
        pytest.skip("There is no user to change password")

    new_password = fauxfactory.gen_alphanumeric()
    rest_user.action.edit(password=new_password)
    cred = Credential(principal=rest_user.userid, secret=new_password)
    new_user = User(credential=cred)
    login(new_user)


@pytest.fixture(scope='function')
def rates(request, rest_api):
    chargeback = rest_api.collections.chargebacks.find_by(rate_type='Compute')[0]
    data = [{
        'description': 'test_rate_{}_{}'.format(_index, fauxfactory.gen_alphanumeric()),
        'rate': 1,
        'group': 'cpu',
        'per_time': 'daily',
        'per_unit': 'megahertz',
        'chargeback_rate_id': chargeback.id
    } for _index in range(0, 3)]

    rates = rest_api.collections.rates.action.create(*data)
    for rate in data:
        wait_for(
            lambda: rest_api.collections.rates.find_by(description=rate.get('description')),
            num_sec=180,
            delay=10,
        )

    @request.addfinalizer
    def _finished():
        ids = [rate.id for rate in rates]
        delete_rates = [rate for rate in rest_api.collections.rates if rate.id in ids]
        if len(delete_rates) != 0:
            rest_api.collections.rates.action.delete(*delete_rates)

    return rates


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_edit_rates(rest_api, rates, multiple):
    if multiple:
        new_descriptions = []
        rates_data_edited = []
        for rate in rates:
            new_description = fauxfactory.gen_alphanumeric().lower()
            new_descriptions.append(new_description)
            rate.reload()
            rates_data_edited.append({
                "href": rate.href,
                "description": "test_category_{}".format(new_description),
            })
        rest_api.collections.rates.action.edit(*rates_data_edited)
        for new_description in new_descriptions:
            wait_for(
                lambda: rest_api.collections.rates.find_by(description=new_description),
                num_sec=180,
                delay=10,
            )
    else:
        rate = rest_api.collections.rates.find_by(description=rates[0].description)[0]
        new_description = 'test_rate_{}'.format(fauxfactory.gen_alphanumeric().lower())
        rate.action.edit(description=new_description)
        wait_for(
            lambda: rest_api.collections.categories.find_by(description=new_description),
            num_sec=180,
            delay=10,
        )


@pytest.mark.uncollectif(lambda: version.current_version() < '5.5')
@pytest.mark.parametrize(
    "multiple", [False, True],
    ids=["one_request", "multiple_requests"])
def test_delete_rates(rest_api, rates, multiple):
    if multiple:
        rest_api.collections.rates.action.delete(*rates)
        with error.expected("ActiveRecord::RecordNotFound"):
            rest_api.collections.rates.action.delete(*rates)
    else:
        rate = rates[0]
        rate.action.delete()
        with error.expected("ActiveRecord::RecordNotFound"):
            rate.action.delete()


COLLECTIONS_IGNORED_53 = {
    "availability_zones", "conditions", "events", "flavors", "policy_actions", "security_groups",
    "tags", "tasks",
}

COLLECTIONS_IGNORED_54 = {
    "features", "pictures", "provision_dialogs", "rates", "results", "service_dialogs",
}


@pytest.mark.parametrize(
    "collection_name",
    ["availability_zones", "chargebacks", "clusters", "conditions", "data_stores", "events",
    "features", "flavors", "groups", "hosts", "pictures", "policies", "policy_actions",
    "policy_profiles", "provision_dialogs", "rates", "request_tasks", "requests", "resource_pools",
    "results", "roles", "security_groups", "servers", "service_dialogs", "service_requests",
    "tags", "tasks", "templates", "users", "vms", "zones"])
@pytest.mark.uncollectif(
    lambda collection_name: (
        collection_name in COLLECTIONS_IGNORED_53 and current_version() < "5.4") or (
            collection_name in COLLECTIONS_IGNORED_54 and current_version() < "5.5"))
def test_query_simple_collections(rest_api, collection_name):
    """This test tries to load each of the listed collections. 'Simple' collection means that they
    have no usable actions that we could try to run
    Steps:
        * GET /api/<collection_name>
    Metadata:
        test_flag: rest
    """
    collection = getattr(rest_api.collections, collection_name)
    collection.reload()
    list(collection)

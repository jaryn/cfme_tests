from cached_property import cached_property
from os import path

from wrapanapi.containers.providers.openshift import Openshift

from . import ContainersProvider

from cfme.containers.provider import (
    ContainersProviderDefaultEndpoint, ContainersProviderEndpointsForm
)
from cfme.common.provider import DefaultEndpoint
from cfme.utils.ocp_cli import OcpCli
from cfme.utils.path import data_path
from cfme.utils.varmeth import variable
from cfme.utils.version import current_version


class CustomAttribute(object):
    def __init__(self, name, value, field_type=None, href=None):
        self.name = name
        self.value = value
        self.field_type = field_type
        self.href = href


class OpenshiftDefaultEndpoint(ContainersProviderDefaultEndpoint):
    """Represents Openshift default endpoint"""
    @staticmethod
    def get_ca_cert():
        """Getting OpenShift's certificate from the master machine.
        Args:
           No args.
        returns:
            certificate's content.
        """
        cert_file_path = path.join(str(data_path), 'cert-auths', 'cmqe-tests-openshift-signer.crt')
        with open(cert_file_path) as f:
            return f.read()


class HawkularEndpoint(DefaultEndpoint):
    """Represents Hawkular Endpoint"""
    name = 'hawkular'

    @property
    def view_value_mapping(self):
        out = {
            'hostname': self.hostname,
            'api_port': self.api_port
        }
        if current_version() >= '5.8':
            out['sec_protocol'] = self.sec_protocol
            if self.sec_protocol.lower() == 'ssl trusting custom ca':
                out['trusted_ca_certificates'] = OpenshiftDefaultEndpoint.get_ca_cert()
        return out


class AlertsEndpoint(DefaultEndpoint):
    """Represents Alerts Endpoint"""
    name = 'alerts'

    @property
    def view_value_mapping(self):
        if current_version() > '5.9':
            out = {
                'hostname': self.hostname,
                'api_port': self.api_port
            }
            if current_version() >= '5.8':
                out['sec_protocol'] = self.sec_protocol
                if self.sec_protocol.lower() == 'ssl trusting custom ca':
                    out['trusted_ca_certificates'] = OpenshiftDefaultEndpoint.get_ca_cert()
            return out
        else:
            return {}


class OpenshiftProvider(ContainersProvider):
    num_route = ['num_route']
    STATS_TO_MATCH = ContainersProvider.STATS_TO_MATCH + num_route
    type_name = "openshift"
    mgmt_class = Openshift
    db_types = ["Openshift::ContainerManager"]
    endpoints_form = ContainersProviderEndpointsForm

    def __init__(
            self,
            name=None,
            key=None,
            zone=None,
            metrics_type=None,
            alerts_type=None,
            provider_data=None,
            endpoints=None,
            appliance=None,
            http_proxy=None,
            adv_http=None,
            adv_https=None,
            no_proxy=None,
            image_repo=None,
            image_reg=None,
            image_tag=None,
            cve_loc=None):

        gt_59 = True if self.appliance.version >= '5.9' else False

        self.http_proxy = http_proxy if gt_59 else None
        self.adv_http = adv_http if gt_59 else None
        self.adv_https = adv_https if gt_59 else None
        self.no_proxy = no_proxy if gt_59 else None
        self.image_repo = image_repo if gt_59 else None
        self.image_reg = image_reg if gt_59 else None
        self.image_tag = image_tag if gt_59 else None
        self.cve_loc = cve_loc if gt_59 else None

        super(OpenshiftProvider, self).__init__(
            name=name,
            key=key,
            zone=zone,
            metrics_type=metrics_type,
            provider_data=provider_data,
            alerts_type=alerts_type,
            endpoints=endpoints,
            appliance=appliance)

    @cached_property
    def cli(self):
        return OcpCli(self)

    def href(self):
        return self.appliance.rest_api.collections.providers\
            .find_by(name=self.name).resources[0].href

    @property
    def view_value_mapping(self):

        mapping = {
            'name': self.name,
            'zone': self.zone,
            'metrics_type': self.metrics_type,
            'alerts_type': self.alerts_type
        }

        mapping['prov_type'] = (
            'OpenShift Container Platform'
            if self.appliance.is_downstream
            else 'OpenShift')

        mapping['proxy'] = {
            'http_proxy': self.http_proxy
        }

        mapping['advanced'] = {
            'adv_http': self.adv_http,
            'adv_https': self.adv_https,
            'no_proxy': self.no_proxy,
            'image_repo': self.image_repo,
            'image_reg': self.image_reg,
            'image_tag': self.image_tag,
            'cve_loc': self.cve_loc
        }

        return mapping

    @variable(alias='db')
    def num_route(self):
        return self._num_db_generic('container_routes')

    @num_route.variant('ui')
    def num_route_ui(self):
        return int(self.get_detail("Relationships", "Routes"))

    @variable(alias='db')
    def num_template(self):
        return self._num_db_generic('container_templates')

    @num_template.variant('ui')
    def num_template_ui(self):
        return int(self.get_detail("Relationships", "Container Templates"))

    @classmethod
    def from_config(cls, prov_config, prov_key, appliance=None):

        endpoints = {}
        token_creds = cls.process_credential_yaml_key(prov_config['credentials'], cred_type='token')
        for endp in prov_config['endpoints']:
            if OpenshiftDefaultEndpoint.name == endp:
                prov_config['endpoints'][endp]['token'] = token_creds.token
                endpoints[endp] = OpenshiftDefaultEndpoint(**prov_config['endpoints'][endp])
            elif HawkularEndpoint.name == endp:
                endpoints[endp] = HawkularEndpoint(**prov_config['endpoints'][endp])
            elif AlertsEndpoint.name == endp:
                endpoints[endp] = AlertsEndpoint(**prov_config['endpoints'][endp])
            # TODO Add Prometheus and logic for having to select or the other based on metrcis_type
            else:
                raise Exception('Unsupported endpoint type "{}".'.format(endp))

        http_proxy = prov_config.get('settings', {}).get('proxy', {}).get('http_proxy')
        adv_http = prov_config.get('settings', {}).get('advanced', {}).get('adv_http')
        adv_https = prov_config.get('settings', {}).get('advanced', {}).get('adv_https')
        no_proxy = prov_config.get('settings', {}).get('advanced', {}).get('no_proxy')
        image_repo = prov_config.get('settings', {}).get('advanced', {}).get('image_repo')
        image_reg = prov_config.get('settings', {}).get('advanced', {}).get('image_reg')
        image_tag = prov_config.get('settings', {}).get('advanced', {}).get('image_tag')
        cve_loc = prov_config.get('settings', {}).get('advanced', {}).get('cve_loc')

        return cls(
            name=prov_config.get('name'),
            key=prov_key,
            zone=prov_config.get('server_zone'),
            metrics_type=prov_config.get('metrics_type'),
            alerts_type=prov_config.get('alerts_type'),
            endpoints=endpoints,
            provider_data=prov_config,
            appliance=appliance,
            http_proxy=http_proxy,
            adv_http=adv_http,
            adv_https=adv_https,
            no_proxy=no_proxy,
            image_repo=image_repo,
            image_reg=image_reg,
            image_tag=image_tag,
            cve_loc=cve_loc
        )

    def custom_attributes(self):
        """returns custom attributes"""
        response = self.appliance.rest_api.get(
            path.join(self.href(), 'custom_attributes'))
        out = []
        for attr_dict in response['resources']:
            attr = self.appliance.rest_api.get(attr_dict['href'])
            out.append(
                CustomAttribute(
                    attr['name'], attr['value'],
                    (attr['field_type'] if 'field_type' in attr else None),
                    attr_dict['href']
                )
            )
        return out

    def add_custom_attributes(self, *custom_attributes):
        """Adding static custom attributes to provider.
        Args:
            custom_attributes: The custom attributes to add.
        returns: response.
        """
        if not custom_attributes:
            raise TypeError('{} takes at least 1 argument.'
                            .format(self.add_custom_attributes.__name__))
        for attr in custom_attributes:
            if not isinstance(attr, CustomAttribute):
                raise TypeError('All arguments should be of type {}. ({} != {})'
                                .format(CustomAttribute, type(attr), CustomAttribute))
        payload = {
            "action": "add",
            "resources": [{
                "name": ca.name,
                "value": str(ca.value)
            } for ca in custom_attributes]}
        for i, fld_tp in enumerate([attr.field_type for attr in custom_attributes]):
            if fld_tp:
                payload['resources'][i]['field_type'] = fld_tp
        return self.appliance.rest_api.post(
            path.join(self.href(), 'custom_attributes'), **payload)

    def edit_custom_attributes(self, *custom_attributes):
        """Editing static custom attributes in provider.
        Args:
            custom_attributes: The custom attributes to edit.
        returns: response.
        """
        if not custom_attributes:
            raise TypeError('{} takes at least 1 argument.'
                            .format(self.edit_custom_attributes.__name__))
        for attr in custom_attributes:
            if not isinstance(attr, CustomAttribute):
                raise TypeError('All arguments should be of type {}. ({} != {})'
                                .format(CustomAttribute, type(attr), CustomAttribute))
        attribs = self.custom_attributes()
        payload = {
            "action": "edit",
            "resources": [{
                "href": filter(lambda attr: attr.name == ca.name, attribs)[-1].href,
                "value": ca.value
            } for ca in custom_attributes]}
        return self.appliance.rest_api.post(
            path.join(self.href(), 'custom_attributes'), **payload)

    def delete_custom_attributes(self, *custom_attributes):
        """Deleting static custom attributes from provider.

        Args:
            custom_attributes: The custom attributes to delete.
                               (Could be also names (str))
        Returns: response.
        """
        names = []
        for attr in custom_attributes:
            attr_type = type(attr)
            if attr_type in (str, CustomAttribute):
                names.append(attr if attr_type is str else attr.name)
            else:
                raise TypeError('Type of arguments should be either'
                                'str or CustomAttribute. ({} not in [str, CustomAttribute])'
                                .format(type(attr)))
        attribs = self.custom_attributes()
        if not names:
            names = [attr.name for attr in attribs]
        payload = {
            "action": "delete",
            "resources": [{
                "href": attr.href,
            } for attr in attribs if attr.name in names]}
        return self.appliance.rest_api.post(
            path.join(self.href(), 'custom_attributes'), **payload)

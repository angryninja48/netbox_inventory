#!/usr/bin/env python

import argparse

try:
    import requests
except ImportError:
    sys.exit('Requires python requests to run')

try:
    import json
except ImportError:
    import simplejson as json


class NetboxInventory(object):

    def __init__(self,args,netbox_server,netbox_protocol='http',netbox_port=80,netbox_token=None):

        self.inventory = {}

        self.netbox_protocol = netbox_protocol
        self.netbox_server = netbox_server
        self.netbox_port = netbox_port

        self.base_url = '{0}://{1}:{2}'.format(
            self.netbox_protocol,
            self.netbox_server,
            self.netbox_port
        )

        self.netbox_token = netbox_token

        if self.netbox_token:
           self.headers = {
                'Authorization': self.netbox_token,
                'Accept': 'application/json',
                'Content-Type': 'application/json'
                }
        self.session = requests.Session()

        self.list = args.list
        self.host = args.host

        if self.list:
            self.devices = self._process_devices()
            self.inventory = self.create_inventory_output(self.devices)
        # Not implemented as we use "_meta"
        elif self.host:
            self.inventory = self._empty_inventory()
        else:
            self.inventory = self._empty_inventory()

        print(json.dumps(self.inventory))

    def _api_call(self,api_endpoint):
        """
        Return the Output an API Call
        """
        api_url = '{0}/api/{1}'.format(self.base_url, api_endpoint)

        response = self.session.get(api_url, headers=self.headers)

        # Exit if return code not 200
        response.raise_for_status()
        return response.json()


    def _device_list(self):
        """
        Return devices from /dcim/devices API call
        """
        return self._api_call("dcim/devices")


    def _device_interfaces(self, device_id):
        """
        Return a list of interfaces for a device given an id
        """
        interfaces = self._api_call('dcim/interfaces/?device_id={0}'.format(device_id))
        return interfaces['results']

    def _interface_ip(self, interface_id):
        """
        Return a list of ip addresses given an interface id
        """
        interfaces_ip = self._api_call('ipam/ip-addresses/?interface_id={0}'.format(interface_id))
        return interfaces_ip['results']

    def _device_primary_ip(self, device_id):
        """
        Returns the IP address used to manage the device
        """
        primary_ip = self._api_call('dcim/devices/{0}'.format(device_id))
        if primary_ip['primary_ip']:
            # Strip netmask from value
            return primary_ip['primary_ip']['address'].split('/')[0]
        else:
            return None

    def _device_ssh_port(self, device_id):
        """
        Temporary Hackish API call using ASN custom field
        """
        port_number = self._api_call('dcim/devices/{0}'.format(device_id))
        if port_number['custom_fields']:
            return port_number['custom_fields']['ASN']
        else:
            return None

    def _process_interface_vlans(self, device_id):
        """
        Returns a list of interfaces for a device with associated vlans (tagged and untagged)
        """
        interfaces = self._device_interfaces(device_id)
        interface_list = []
        for interface in interfaces:
            tagged_vlan_list = []
            if interface['tagged_vlans']:
                tagged_vids = interface['tagged_vlans']
                for tagged_vid in tagged_vids:
                    tagged_vlan_list.append(tagged_vid['vid'])
            if interface['untagged_vlan']:
                untagged_vid = interface['untagged_vlan']['vid']
            else:
                untagged_vid = None

            # Create an interface hash
            vlan_map = {
                'interface': interface['name'],
                'int_id': interface['id'],
                'untagged_vlan': untagged_vid,
                'tagged_vlans': tagged_vlan_list
                }

            interface_list.append(vlan_map)

        return interface_list


    def _process_devices(self):
        """
        Loops through device list and assigns applicable hostvars
        """
        devices = self._device_list()
        device_list = []

        # Create device list and assign variables to devices
        for device in devices['results']:
            interfaces = self._device_interfaces(device['id'])
            vlans = self._process_interface_vlans(device['id'])
            device_ip = self._device_primary_ip(device['id'])
            device_ssh_port = self._device_ssh_port(device['id'])

            int_list = []
            for interface in interfaces:
                int_name = interface['name']
                int_id = interface['id']
                ip_addr = self._interface_ip(int_id)

                interface_hash = {
                    'interface_name': int_name,
                    'interface_id': int_id,
                    'ip_address': ip_addr
                }
                int_list.append(interface_hash)

            device_hash = {
                'id': device['id'],
                'ansible_ssh_host': device_ip,
                'ansible_ssh_port': device_ssh_port,
                'name': device['name'],
                'interfaces': int_list,
                'vlans': vlans
                }
            device_list.append(device_hash)

        return device_list

    def create_inventory_output(self, devices):
        """
        Create Ansible Inventory JSON
        Example:
        {
            'eos': {
                'hosts': ['arista01', 'arista02'],
                'vars': {
                    'ansible_ssh_user': 'vagrant',
                    'ansible_network_os': 'eos',
                    'ansible_ssh_private_key_file':
                        '~/.vagrant.d/insecure_private_key'
                }
            },
            '_meta': {
                'hostvars': {
                    'arista01': {
                        'ansible_ssh_port': '2222',
                        'ansible_ssh_host': '127.0.0.1'
                    },
                    'arista02': {
                        'host_specific_var': 'bar'
                    }
                }
            }
        }
        """
        # create base json hash
        result = {
            "all": {
                "hosts": [],
                "vars": {}
            },
            "_meta": {
                "hostvars": {}
                }
            }


        _device = result['_meta']['hostvars']
        _all_group = result['all']
        _all_group['vars'] = {
                'ansible_ssh_user': 'vagrant',
                'ansible_network_os': 'eos',
                'ansible_ssh_private_key_file': '~/.vagrant.d/insecure_private_key'
                }

        #  create dict for each device
        for device in devices:
            name = device['name']
            _device[name] = {
                            'ansible_host': device['ansible_ssh_host'],
                            'ansible_port': device['ansible_ssh_port'],
                            'interfaces': device['interfaces'],
                            'vlans': device['vlans']
                            }
            _all_group['hosts'].append(name)

        return result

    # Returns an empty inventory
    def _empty_inventory(self):
        return {'_meta': {'hostvars': {}}}


def cli_arguments():
    """
    Parse arguements - By default ansible uses --list
    """

    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--list",action="store_true")
    parser.add_argument("--host",action="store")
    arguments = parser.parse_args()
    return arguments

def main():
    """
    Main process
    """
    args = cli_arguments()
    token = '0123456789abcdef0123456789abcdefghijh231'
    netbox_server = 'netbox01.lab'

    netbox = NetboxInventory(args=args, netbox_server=netbox_server, netbox_token=token)

if __name__ == "__main__":
    main()

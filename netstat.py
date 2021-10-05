"""
netstat - Network Manager connection stat reporting service
"""

import dbus
import dbus.exceptions
from syslog import syslog
import json
import socket
import struct

# Network Manager Device Connection States
NM_DEVICE_STATE_UNKNOWN = 0
NM_DEVICE_STATE_UNMANAGED = 10
NM_DEVICE_STATE_UNAVAILABLE = 20
NM_DEVICE_STATE_DISCONNECTED = 30
NM_DEVICE_STATE_PREPARE = 40
NM_DEVICE_STATE_CONFIG = 50
NM_DEVICE_STATE_NEED_AUTH = 60
NM_DEVICE_STATE_IP_CONFIG = 70
NM_DEVICE_STATE_IP_CHECK = 80
NM_DEVICE_STATE_SECONDARIES = 90
NM_DEVICE_STATE_ACTIVATED = 100
NM_DEVICE_STATE_DEACTIVATING = 110
NM_DEVICE_STATE_FAILED = 120

# values from https://developer-old.gnome.org/NetworkManager/stable/nm-dbus-types.html#NMDeviceState
DEVICE_STATE_DESCRIPTIONS = {
    NM_DEVICE_STATE_UNKNOWN:        'Unknown',
    NM_DEVICE_STATE_UNMANAGED:      'Unmanaged',
    NM_DEVICE_STATE_UNAVAILABLE:    'Unavailable',
    NM_DEVICE_STATE_DISCONNECTED:   'Disconnected',
    NM_DEVICE_STATE_PREPARE:        'Preparing',
    NM_DEVICE_STATE_CONFIG:         'Connecting',
    NM_DEVICE_STATE_NEED_AUTH:      'Needs more information',
    NM_DEVICE_STATE_IP_CONFIG:      'Requesting IP addresses and routing information',
    NM_DEVICE_STATE_IP_CHECK:       'Checking for further required action',
    NM_DEVICE_STATE_SECONDARIES:    'Waiting for secondary connection',
    NM_DEVICE_STATE_ACTIVATED:      'Activated',
    NM_DEVICE_STATE_DEACTIVATING:   'Deactivating',
    NM_DEVICE_STATE_FAILED:         'Failed'
}

# Network Manager Device Types
NM_DEVICE_TYPE_UNKNOWN      = 0
NM_DEVICE_TYPE_ETHERNET     = 1
NM_DEVICE_TYPE_WIFI         = 2
NM_DEVICE_TYPE_UNUSED1      = 3
NM_DEVICE_TYPE_UNUSED2      = 4
NM_DEVICE_TYPE_BT           = 5
NM_DEVICE_TYPE_OLPC_MESH    = 6
NM_DEVICE_TYPE_WIMAX        = 7
NM_DEVICE_TYPE_MODEM        = 8
NM_DEVICE_TYPE_INFINIBAND   = 9
NM_DEVICE_TYPE_BOND         = 10
NM_DEVICE_TYPE_VLAN         = 11
NM_DEVICE_TYPE_ADSL         = 12
NM_DEVICE_TYPE_BRIDGE       = 13
NM_DEVICE_TYPE_GENERIC      = 14
NM_DEVICE_TYPE_TEAM         = 15
NM_DEVICE_TYPE_TUN          = 16
NM_DEVICE_TYPE_IP_TUNNEL    = 17
NM_DEVICE_TYPE_MACVLAN      = 18
NM_DEVICE_TYPE_VXLAN        = 19
NM_DEVICE_TYPE_VETH         = 20

# Useful Network Manager Active Connection States
NM_ACTIVE_CONNECTION_STATE_UNKNOWN      = 0
NM_ACTIVE_CONNECTION_STATE_ACTIVATING   = 1
NM_ACTIVE_CONNECTION_STATE_ACTIVATED    = 2
NM_ACTIVE_CONNECTION_STATE_DEACTIVATING = 3
NM_ACTIVE_CONNECTION_STATE_DEACTIVATED  = 4

# values from https://developer-old.gnome.org/NetworkManager/stable/nm-dbus-types.html#NMActiveConnectionState
ACTIVE_CONNECTION_STATE_DESCRIPTIONS = {
    NM_ACTIVE_CONNECTION_STATE_UNKNOWN:         'Unknown',
    NM_ACTIVE_CONNECTION_STATE_ACTIVATING:      'Activating',
    NM_ACTIVE_CONNECTION_STATE_ACTIVATED:       'Activated',
    NM_ACTIVE_CONNECTION_STATE_DEACTIVATING:    'Deactivating',
    NM_ACTIVE_CONNECTION_STATE_DEACTIVATED:     'Deactivated',
}

NM_IFACE = 'org.freedesktop.NetworkManager'
NM_SETTINGS_IFACE = 'org.freedesktop.NetworkManager.Settings'
NM_SETTINGS_OBJ = '/org/freedesktop/NetworkManager/Settings'
NM_OBJ = '/org/freedesktop/NetworkManager'
NM_CONNECTION_IFACE = 'org.freedesktop.NetworkManager.Settings.Connection'
NM_DEVICE_IFACE = 'org.freedesktop.NetworkManager.Device'
NM_WIFI_DEVICE_IFACE = 'org.freedesktop.NetworkManager.Device.Wireless'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
NM_CONNECTION_ACTIVE_IFACE = 'org.freedesktop.NetworkManager.Connection.Active'
NM_AP_IFACE = 'org.freedesktop.NetworkManager.AccessPoint'
NM_IP4CONFIG_IFACE = 'org.freedesktop.NetworkManager.IP4Config'
NM_IP6CONFIG_IFACE = 'org.freedesktop.NetworkManager.IP6Config'

class NetStat():
    """ NetworkManager connection stats reporting service
    """

    def __init__(self, connection_stat_changed_signal):
        try:
            self.bus = dbus.SystemBus()
            self.nm = dbus.Interface(self.bus.get_object(NM_IFACE, NM_OBJ), NM_IFACE)
            self.nm_props = dbus.Interface(self.bus.get_object(NM_IFACE, NM_OBJ), DBUS_PROP_IFACE)
            # self.nm_settings = dbus.Interface(self.bus.get_object(NM_IFACE, NM_SETTINGS_OBJ), NM_SETTINGS_IFACE)
            self.nm_props.connect_to_signal('PropertiesChanged', self.nm_props_changed)
            self.connection_stats_changed = connection_stat_changed_signal
            self.connection_stats = {}
            self.update_connection_stats()
        except dbus.DBusException:
            pass

    def nm_props_changed(self, iface, props_changed, props_invalidated):
        """ Signal callback for change to Network Manager properties
        """

        # Trigger an update of the connection stats
        self.update_connection_stats()

    def generate_boilerplate_stat_entry(self, props: dict) -> dict:
        """
        Generate the boilerplate connection stats data that is common
        to any interface

        :param props: dict of properties from the target device
        :return: initial dict of stats for the target device to be updated
        """
        # Generate a new stat entry object
        new_stat_entry = {}

        # Grab device state
        new_stat_entry["device-state"] = DEVICE_STATE_DESCRIPTIONS[props["State"]]

        # Pre-populate default empty values
        new_stat_entry["connection-id"] = ""
        new_stat_entry["mac-address"] = ""
        new_stat_entry["ipv4-address-data"] = []
        new_stat_entry["ipv4-gateway"] = ""
        new_stat_entry["ipv4-nameservers"] = []
        new_stat_entry["ipv6-address-data"] = []
        new_stat_entry["ipv6-gateway"] = ""
        new_stat_entry["ipv6-nameservers"] = []

        return new_stat_entry

    def populate_ip_data(self, dev_path: str, stat_entry: dict) -> None:
        """
        Populate the IPv4/v6 stats for the target interface

        :param dev_path: DBus path representing the target interface
        :param stat_entry: dict of stats for the target device to be updated
        """
        prop_iface = dbus.Interface(self.bus.get_object(NM_IFACE, dev_path), DBUS_PROP_IFACE)

        # Grab IPv4 data
        ipv4_config_proxy = self.bus.get_object(NM_IFACE, prop_iface.Get(NM_DEVICE_IFACE, "Ip4Config"))
        ipv4_config_iface = dbus.Interface(ipv4_config_proxy, DBUS_PROP_IFACE)

        ipv4_addresses = []
        for address in ipv4_config_iface.Get(NM_IP4CONFIG_IFACE, "AddressData"):
            ipv4_addresses.append(str(address['address']) + "/" + str(address['prefix']))

        ipv4_nameservers = []
        for nameserver in ipv4_config_iface.Get(NM_IP4CONFIG_IFACE, "Nameservers"):
            # IPv4 DNS nameservers are returned as an array of dbus.UInt32's,
            # so we need to unpack them
            nameserver_string = socket.inet_ntoa(struct.pack('=L', nameserver))
            ipv4_nameservers.append(nameserver_string)

        stat_entry["ipv4-address-data"] = ipv4_addresses
        stat_entry["ipv4-gateway"] = str(ipv4_config_iface.Get(NM_IP4CONFIG_IFACE, "Gateway"))
        stat_entry["ipv4-nameservers"] = ipv4_nameservers

        # Grab IPv6 data
        ipv6_config_proxy = self.bus.get_object(NM_IFACE, prop_iface.Get(NM_DEVICE_IFACE, "Ip6Config"))
        ipv6_config_iface = dbus.Interface(ipv6_config_proxy, DBUS_PROP_IFACE)

        ipv6_addresses = []
        for address in ipv6_config_iface.Get(NM_IP6CONFIG_IFACE, "AddressData"):
            ipv6_addresses.append(str(address['address']) + "/" + str(address['prefix']))

        ipv6_nameservers = []
        for nameserver in ipv6_config_iface.Get(NM_IP6CONFIG_IFACE, "Nameservers"):
            # IPv6 nameservers are returned as an array of arrays of bytes, so
            # we need to convert this back to a string
            nameserver_string = socket.inet_ntop(socket.AF_INET6, bytes(nameserver))
            ipv6_nameservers.append(nameserver_string)

        stat_entry["ipv6-address-data"] = ipv6_addresses
        stat_entry["ipv6-gateway"] = str(ipv6_config_iface.Get(NM_IP6CONFIG_IFACE, "Gateway"))
        stat_entry["ipv6-nameservers"] = ipv6_nameservers

    def generate_ethernet_stat_entry(self, dev_path: str) -> dict:
        """
        Generate the connection stats for an Ethernet interface

        :param dev_path: DBus path representing the target interface
        :return: dict of stats for the target interface
        """
        props_iface = dbus.Interface(self.bus.get_object(NM_IFACE, dev_path), DBUS_PROP_IFACE)
        props = props_iface.GetAll(NM_DEVICE_IFACE)

        new_stat_entry = self.generate_boilerplate_stat_entry(props)
        new_stat_entry["mac-address"] = str(props["HwAddress"])

        if props["State"] == NM_DEVICE_STATE_ACTIVATED:
            active_connection = props_iface.Get(NM_DEVICE_IFACE, "ActiveConnection")
            active_connection_prop_iface = dbus.Interface(self.bus.get_object(NM_IFACE, active_connection), DBUS_PROP_IFACE)

            new_stat_entry["connection-id"] = str(active_connection_prop_iface.Get(NM_CONNECTION_ACTIVE_IFACE, "Id"))
            new_stat_entry["connection-state"] = ACTIVE_CONNECTION_STATE_DESCRIPTIONS[active_connection_prop_iface.Get(NM_CONNECTION_ACTIVE_IFACE, "State")]

            self.populate_ip_data(dev_path, new_stat_entry)

        return new_stat_entry

    def generate_wifi_stat_entry(self, dev_path: str) -> dict:
        """
        Generate the connection stats for a Wi-Fi interface

        :param dev_path: DBus path representing the target interface
        :return: dict of stats for the target interface
        """
        props_iface = dbus.Interface(self.bus.get_object(NM_IFACE, dev_path), DBUS_PROP_IFACE)
        props = props_iface.GetAll(NM_DEVICE_IFACE)

        new_stat_entry = self.generate_boilerplate_stat_entry(props)
        new_stat_entry["mac-address"] = str(props["HwAddress"])

        if props["State"] == NM_DEVICE_STATE_ACTIVATED:
            active_connection = props_iface.Get(NM_DEVICE_IFACE, "ActiveConnection")
            active_connection_prop_iface = dbus.Interface(self.bus.get_object(NM_IFACE, active_connection), DBUS_PROP_IFACE)

            active_connection_connection = active_connection_prop_iface.Get(NM_CONNECTION_ACTIVE_IFACE, "Connection")
            active_connection_connection_iface = dbus.Interface(self.bus.get_object(NM_IFACE, active_connection_connection), NM_CONNECTION_IFACE)
            connection_settings = active_connection_connection_iface.GetSettings()

            new_stat_entry["connection-id"] = str(active_connection_prop_iface.Get(NM_CONNECTION_ACTIVE_IFACE, "Id"))
            new_stat_entry["connection-state"] = ACTIVE_CONNECTION_STATE_DESCRIPTIONS[active_connection_prop_iface.Get(NM_CONNECTION_ACTIVE_IFACE, "State")]

            self.populate_ip_data(dev_path, new_stat_entry)

            if props["DeviceType"] == NM_DEVICE_TYPE_WIFI:
                active_ap_path = props_iface.Get(NM_WIFI_DEVICE_IFACE, "ActiveAccessPoint")
                if active_ap_path != "/":
                    # Wi-Fi interface is currently associated with an AP
                    ap_proxy = self.bus.get_object(NM_IFACE, active_ap_path)
                    ap_props = dbus.Interface(ap_proxy, DBUS_PROP_IFACE)
                    raw_ssid = ap_props.Get(NM_AP_IFACE, "Ssid")

                    ssid = ""
                    for c in raw_ssid:
                        ssid = ssid + chr(c)
                    new_stat_entry["ssid"] = ssid
                    new_stat_entry["strength"] = int(ap_props.Get(NM_AP_IFACE, "Strength"))

                if "802-11-wireless-security" in connection_settings:
                    new_stat_entry["security"] = {}
                    if "auth-alg" in connection_settings["802-11-wireless-security"]:
                        new_stat_entry["security"]["auth-alg"] = str(connection_settings["802-11-wireless-security"]["auth-alg"])

                    if "key-mgmt" in connection_settings["802-11-wireless-security"]:
                        new_stat_entry["security"]["key-mgmt"] = str(connection_settings["802-11-wireless-security"]["key-mgmt"])

                    # Check if enterprise Wi-Fi is being used, and if so, pull in
                    # those settings
                    if "802-1x" in connection_settings:
                        if "eap" in connection_settings["802-1x"]:
                            # connection_settings["802-1x"]["eap"] is a dbus.Array
                            eap_methods = []
                            for eap in connection_settings["802-1x"]["eap"]:
                                eap_methods.append(str(eap))
                            new_stat_entry["security"]["eap"] = eap_methods

                        if "identity" in connection_settings["802-1x"]:
                            new_stat_entry["security"]["identity"] = str(connection_settings["802-1x"]["identity"])

                        if "phase2-auth" in connection_settings["802-1x"]:
                            # connection_settings["802-1x"]["phase2-auth""] is a dbus.Array
                            phase2_auth_methods = []
                            for method in connection_settings["802-1x"]["phase2-auth"]:
                                phase2_auth_methods.append(str(method))
                            new_stat_entry["security"]["phase2-auth"] = phase2_auth_methods

                        if "phase2-autheap" in connection_settings["802-1x"]:
                            # connection_settings["802-1x"]["phase2-autheap""] is a dbus.Array
                            phase2_autheap_methods = []
                            for method in connection_settings["802-1x"]["phase2-autheap"]:
                                phase2_autheap_methods.append(str(method))
                            new_stat_entry["security"]["phase2-autheap"] = phase2_autheap_methods

        return new_stat_entry

    def update_connection_stats(self) -> None:
        """
        Update the connection stats from NetworkManager via DBus
        """
        devices = self.nm.GetDevices()

        connection_stats = {}

        # Loop through devices
        for dev_path in devices:
            try:
                props_iface = dbus.Interface(self.bus.get_object(NM_IFACE, dev_path), DBUS_PROP_IFACE)
                props = props_iface.GetAll(NM_DEVICE_IFACE)

                # Ethernet interface
                if props["DeviceType"] == NM_DEVICE_TYPE_ETHERNET:
                    connection_stats[str(props["Interface"])] = self.generate_ethernet_stat_entry(dev_path)
                # Wi-Fi interface
                elif props["DeviceType"] == NM_DEVICE_TYPE_WIFI:
                    connection_stats[str(props["Interface"])] = self.generate_wifi_stat_entry(dev_path)
                # Other interface
                else:
                    continue
            except Exception as e:
                syslog(f'Error reading device properties: {str(e)}')

        self.connection_stats = connection_stats

        # Fire the handler if defined
        if self.connection_stats_changed != None:
            self.connection_stats_changed(json.dumps(self.connection_stats))

    def set_connection_stats_changed(self, callback_function):
        self.connection_stats_changed = callback_function

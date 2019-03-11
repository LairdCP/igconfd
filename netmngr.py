"""
netmngr - Network Manager functionality for the BLE configuration service
"""

import dbus, dbus.exceptions
from syslog import syslog
import time

''' Network Manager Device Connection States '''
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

''' Network Manager Connectivity States '''
NM_CONNECTIVITY_UNKNOWN = 0
NM_CONNECTIVITY_NONE = 1
NM_CONNECTIVITY_PORTAL = 2
NM_CONNECTIVITY_LIMITED = 3
NM_CONNECTIVITY_FULL = 4

''' Useful Network Manager AP Flags '''
NM_802_11_AP_FLAGS_PRIVACY = 0x00000001

''' Useful Network Manager AP Security Flags '''
NM_802_11_AP_SEC_NONE            = 0x00000000
NM_802_11_AP_SEC_PAIR_WEP40      = 0x00000001
NM_802_11_AP_SEC_PAIR_WEP104     = 0x00000002
NM_802_11_AP_SEC_KEY_MGMT_PSK    = 0x00000100
NM_802_11_AP_SEC_KEY_MGMT_802_1X = 0x00000200

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

IG_CONN_NAME = 'ig-connection'

"""
Create a NetworkManager wireless configuration from
the BLE input configuration data
"""
def create_wireless_config(conn_name, config_data):
    try:
        wireless_config = dbus.Dictionary({
            'connection' : dbus.Dictionary({
                'type' : '802-11-wireless',
                'id' : conn_name,
                'autoconnect' : True,
                'interface-name' : 'wlan0'
                }),
            '802-11-wireless' : dbus.Dictionary({
                'mode' : 'infrastructure',
                'ssid' : dbus.ByteArray(config_data['ssid']),
                'hidden': True
                })
        })
        if 'psk' in config_data:
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                'key-mgmt' : 'wpa-psk',
                'psk' : config_data['psk']
            })
        elif 'wep-key' in config_data:
            if 'wep-index' in config_data:
                wep_index = config_data['wep-index']
            else:
                wep_index = 0
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                'key-mgmt' : 'none',
                'wep-key-type' : 1, # Hexadecimal key
                'wep-key{}'.format(wep_index) : config_data['wep-key']
            })
        elif 'eap' in config_data:
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                'key-mgmt' : 'wpa-eap'
            })
            wireless_config['802-1x'] = dbus.Dictionary({
                'eap' : dbus.Array([config_data['eap']]),
                'identity' : config_data['identity'],
                'password' : config_data['password']
            })
            if 'phase2-auth' in config_data:
                wireless_config['802-1x']['phase2-auth'] = dbus.Array([config_data['phase2-auth']])
        if config_data.get('disable-ipv6', False):
            wireless_config['ipv6'] = dbus.Dictionary({
                'method' : 'auto',
                'ignore-auto-dns' : True,
                'never-default' : True
            })
    except KeyError:
        syslog('Invalid input configuration')
        wireless_config = {}
    return wireless_config

class NetManager():
    """Activation status codes
    """
    ACTIVATION_SUCCESS = 0
    ACTIVATION_PENDING = 1
    ACTIVATION_FAILED_AUTH = -1
    ACTIVATION_FAILED_NETWORK = -2

    def __init__(self):
        bus = dbus.SystemBus()
        self.nm = dbus.Interface(bus.get_object(NM_IFACE, NM_OBJ), NM_IFACE)
        self.nm_props = dbus.Interface(bus.get_object(NM_IFACE, NM_OBJ), DBUS_PROP_IFACE)
        self.nm_settings = dbus.Interface(bus.get_object(NM_IFACE, NM_SETTINGS_OBJ), NM_SETTINGS_IFACE)
        self.wifi_dev_obj = bus.get_object(NM_IFACE, self.nm.GetDeviceByIpIface("wlan0"))
        self.wifi_dev = dbus.Interface(self.wifi_dev_obj, NM_WIFI_DEVICE_IFACE)
        self.wifi_dev_props = dbus.Interface(self.wifi_dev_obj, DBUS_PROP_IFACE)
        self.ap_objs = None
        self.new_conn_obj = None
        self.connectivity = self.nm_props.Get(NM_IFACE, 'Connectivity')
        self.activated = False
        self.activation_status = None
        self.wifi_dev_props.connect_to_signal('PropertiesChanged', self.wifi_dev_props_changed)
        self.nm_props.connect_to_signal('PropertiesChanged', self.nm_props_changed)

    def get_wlan_hw_address(self):
        return str(self.wifi_dev_props.Get(NM_WIFI_DEVICE_IFACE, 'HwAddress'))

    def get_access_points(self, timeout=None, continue_scan=False):
        """ Scan for access points
        """
        if not continue_scan:
            syslog('Obtaining access point list.')
            self.ap_objs = self.wifi_dev.GetAllAccessPoints()
        # NOTE: NetworkManager frequently returns multiple APs for the same SSID,
        # so keep them unique using a dictionary
        ap_dict = {}
        start_time = time.time()
        # Collect APs until the list is emptied, or a timeout
        syslog('Collecting APs with timeout = {}'.format(timeout))
        while self.ap_objs and len(self.ap_objs) > 0 and (not timeout
                or time.time() - start_time < timeout):
            ap_obj = self.ap_objs.pop(0)
            try:
                ap_props = dbus.Interface(dbus.SystemBus().get_object(NM_IFACE, ap_obj), DBUS_PROP_IFACE)
                ssid = ''.join([chr(b) for b in ap_props.Get(NM_AP_IFACE, 'Ssid')])
                ap_dict.setdefault(ssid, {})['ssid'] = ssid
                ap_dict[ssid]['ssid'] = ''.join([chr(b) for b in ap_props.Get(NM_AP_IFACE, 'Ssid')])
                ap_dict[ssid]['strength'] = int(ap_props.Get(NM_AP_IFACE, 'Strength'))
                ap_flags = int(ap_props.Get(NM_AP_IFACE, 'Flags'))
                ap_wpa_flags = int(ap_props.Get(NM_AP_IFACE, 'WpaFlags'))
                ap_rsn_flags = int(ap_props.Get(NM_AP_IFACE, 'RsnFlags'))
                ap_dict[ssid]['wep'] = ((ap_flags & NM_802_11_AP_FLAGS_PRIVACY > 0) and
                                        (ap_wpa_flags == NM_802_11_AP_SEC_NONE) and
                                        (ap_rsn_flags == NM_802_11_AP_SEC_NONE))
                ap_dict[ssid]['psk'] = ((ap_wpa_flags & NM_802_11_AP_SEC_KEY_MGMT_PSK > 0) or
                                        (ap_rsn_flags & NM_802_11_AP_SEC_KEY_MGMT_PSK > 0))
                ap_dict[ssid]['eap'] = ((ap_wpa_flags & NM_802_11_AP_SEC_KEY_MGMT_802_1X > 0) or
                                        (ap_rsn_flags & NM_802_11_AP_SEC_KEY_MGMT_802_1X > 0))
            except dbus.exceptions.DBusException:
                # Can occur as APs are removed, just move on to the next AP
                pass
        return ap_dict.values()

    def activate_connection(self, config_data):
        self.activation_status = self.ACTIVATION_PENDING
        try:
            conn = create_wireless_config(IG_CONN_NAME, config_data)
            self.new_conn_obj = self.nm_settings.AddConnection(conn)
            self.nm.ActivateConnection(self.new_conn_obj, self.wifi_dev_obj, '/')
            return True
        except dbus.exceptions.DBusException as e:
            syslog('Failed to create connection: {}'.format(e))
            return False

    def wifi_dev_props_changed(self, iface, props_changed, props_invalidated):
        """ Signal callback for change to the wlan0 device properties
        """
        if props_changed and 'State' in props_changed:
            syslog('WiFi state changed: {}'.format(props_changed['State']))
            if props_changed['State'] == NM_DEVICE_STATE_ACTIVATED:
                # Make sure this is our connection
                active_conn_obj = self.wifi_dev_props.Get(NM_DEVICE_IFACE, 'ActiveConnection')
                active_conn_props = dbus.Interface(dbus.SystemBus().get_object(NM_IFACE, active_conn_obj), DBUS_PROP_IFACE)
                conn_obj = active_conn_props.Get(NM_CONNECTION_ACTIVE_IFACE, 'Connection')
                if conn_obj == self.new_conn_obj:
                    self.activated = True
                    syslog('New connection was activated!')
                    if self.connectivity == NM_CONNECTIVITY_FULL:
                        self.activation_status = self.ACTIVATION_SUCCESS
            elif props_changed['State'] == NM_DEVICE_STATE_FAILED:
                self.activation_status = self.ACTIVATION_FAILED_AUTH

    def nm_props_changed(self, iface, props_changed, props_invalidated):
        """ Signal callback for change to Network Manager properties
        """
        if props_changed and 'Connectivity' in props_changed:
            self.connectivity = props_changed['Connectivity']
            syslog('Connectivity changed: {}'.format(self.connectivity))
            if self.activated:
                self.activation_status = self.ACTIVATION_SUCCESS

    def get_activation_status(self):
        return self.activation_status

    def activation_cleanup(self):
        if self.new_conn_obj:
            syslog('Removing connection: {}'.format(self.new_conn_obj))
            conn = dbus.Interface(dbus.SystemBus().get_object(NM_IFACE, self.new_conn_obj), NM_CONNECTION_IFACE)
            self.new_conn_obj = None
            self.activated = False
            self.activation_status = None

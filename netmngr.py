"""
netmngr - Network Manager functionality for the BLE configuration service
"""

import dbus, dbus.exceptions
from syslog import syslog
import time

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject


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

OFONO_ROOT_PATH = '/'
OFONO_BUS_NAME = 'org.ofono'
OFONO_MANAGER_IFACE = 'org.ofono.Manager'
OFONO_MODEM_IFACE = 'org.ofono.Modem'
OFONO_SIM_IFACE = 'org.ofono.SimManager'
OFONO_CONNMAN_IFACE = 'org.ofono.ConnectionManager'
OFONO_CONNECTION_IFACE = 'org.ofono.ConnectionContext'

GEMALTO_MODEM_MODEL = 'PLS62-W'

IG_CONN_NAME = 'ig-connection'
PAC_FILE = b'/var/lib/private/autoP.pac'

LTE_CONN_NAME = 'lte-connection'
WWAN_DEV_NAME = 'usb0'
LTE_ROUTE_METRIC = 700

GET_AP_INTERMEDIATE_TIMEOUT = 2
ACTIVATION_INTERMEDIATE_TIMEOUT = 5
ACTIVATION_FAILURE_TIMEOUT = 60
ACTIVATION_TIMER_MS = 500

NM_AUTOCONNECT_PRIORITY = 'autoconnect-priority'
NM_CONNECTION = 'connection'
NM_ID = 'id'
NM_UUID = 'uuid'

CFG_PRIORITY = 'priority'
CFG_SSID = 'ssid'

"""
Create a NetworkManager wireless configuration from
the BLE input configuration data
"""
def create_wireless_config(wlan_mac_addr, config_data):
    try:
        syslog("Creating wireless config out of: " + str(config_data))

        priority = 0
        if 'priority' in config_data:
            priority = config_data['priority']

        wireless_config = dbus.Dictionary({
            dbus.String('connection') : dbus.Dictionary({
                dbus.String('type') : dbus.String('802-11-wireless'),
                dbus.String('id') : config_data['ssid'].encode(),
                dbus.String('autoconnect') : True,
                dbus.String('autoconnect-priority') : priority,
                dbus.String('interface-name') : dbus.String('wlan0')
                }),
            dbus.String('802-11-wireless') : dbus.Dictionary({
                dbus.String('mode') : dbus.String('infrastructure'),
                dbus.String('ssid') : dbus.ByteArray(config_data['ssid'].encode()),
                dbus.String('hidden') : False
                })
        })
        if 'psk' in config_data:
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                dbus.String('key-mgmt') : dbus.String('wpa-psk'),
                dbus.String('psk') : config_data['psk'].encode()
            })
        elif 'wep-key' in config_data:
            if 'wep-index' in config_data:
                wep_index = config_data['wep-index']
            else:
                wep_index = 0
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                dbus.String('key-mgmt') : dbus.String('none'),
                dbus.String('wep-key-type') : 1, # Hexadecimal key
                dbus.String('wep-key{}'.format(wep_index)) : config_data['wep-key'].encode()
            })
        elif 'eap' in config_data:
            wireless_config['802-11-wireless-security'] = dbus.Dictionary({
                dbus.String('key-mgmt') : dbus.String('wpa-eap')
            })
            wireless_config['802-1x'] = dbus.Dictionary({
                dbus.String('eap') : dbus.Array([dbus.String(config_data['eap'])])
            })
            if 'identity' in config_data:
                wireless_config['802-1x']['identity'] = config_data['identity'].encode()
            if 'password' in config_data:
                wireless_config['802-1x']['password'] = config_data['password'].encode()
            if 'fast' == config_data['eap']:
                wireless_config['802-1x']['anonymous-identity'] = 'FAST-'+wlan_mac_addr
                wireless_config['802-1x']['phase1-fast-provisioning'] = 3
                wireless_config['802-1x']['pac-file'] = PAC_FILE
                wireless_config['802-1x']['phase2-auth'] = dbus.Array([b'gtc', b'mschapv2'])
            elif 'phase2-auth' in config_data:
                wireless_config['802-1x']['phase2-auth'] = dbus.Array([config_data['phase2-auth']])

        if config_data.get('disable-ipv6', False):
            wireless_config['ipv6'] = dbus.Dictionary({
                dbus.String('method') : dbus.String('auto'),
                dbus.String('ignore-auto-dns') : True,
                dbus.String('never-default') : True
            })
    except KeyError as k:
        syslog('Invalid input configuration: %s' % str(k))
        wireless_config = {}
    except Exception as e:
        syslog('Failed to create wireless config %s' % str(e))
        wireless_config = {}

    return wireless_config

"""
Update a NetworkManager wireless configuration
"""
def update_wireless_config(orig_config, new_config):
    syslog("Updating wireless config with: " + str(new_config))

    # Set priority from new configuration
    if 'connection' in new_config and 'autoconnect-priority' in new_config['connection']:
        orig_config['connection']['autoconnect-priority'] = new_config['connection']['autoconnect-priority']

    # Merge IPv6 settings from new configuration
    if 'ipv6' in new_config:
        orig_config['ipv6'].update(new_config['ipv6'])

    # Update security if the new configuration is different type or
    # contains authentication
    if '802-11-wireless-security' in new_config and 'key-mgmt' in new_config['802-11-wireless-security']:
        if new_config['802-11-wireless-security']['key-mgmt'] != orig_config['802-11-wireless-security']['key-mgmt']:
            # Different type, merge in new configuration
            orig_config['802-11-wireless-security'].update(new_config['802-11-wireless-security'])
            if '802-1x' in new_config:
                orig_config['802-1x'] = new_config['802-1x']
        elif 'psk' in new_config['802-11-wireless-security']:
            # Update PSK
            orig_config['802-11-wireless-security']['psk'] = new_config['802-11-wireless-security']['psk']
        elif '802-1x' in new_config:
            # Update EAP with new configuration
            orig_config['802-1x'].update(new_config['802-1x'])
    return orig_config

def create_lte_conn(conn_name, ifname):
    return dbus.Dictionary({
        b'connection' : dbus.Dictionary({
            b'type' : b'802-3-ethernet',
            b'id' : conn_name.encode(),
            b'autoconnect' : True,
            b'autoconnect-retries' : 0,
            b'interface-name' : ifname.encode(),
            b'metered' : 1,
            }),
        b'ipv4' : dbus.Dictionary({
            b'method' : b'auto',
            b'route-metric' : LTE_ROUTE_METRIC,
            }),
        b'ipv6' : dbus.Dictionary({
            b'method' : b'auto',
            b'route-metric' : LTE_ROUTE_METRIC,
            }),
    })

class NetManager():
    """Activation status codes
    """

    ACTIVATION_SUCCESS = 0
    ACTIVATION_PENDING = 1
    ACTIVATION_INVALID = -1
    ACTIVATION_FAILED_AUTH = -3
    ACTIVATION_FAILED_NETWORK = -2
    ACTIVATION_NO_CONN = -5
    ACTIVATION_NO_SIM = -8

    AP_SCANNING_SUCCESS = 0
    AP_SCANNING = 1

    def __init__(self, response_cb):
        try:
            self.api_enabled = False
            self.bus = dbus.SystemBus()
            self.nm = dbus.Interface(self.bus.get_object(NM_IFACE, NM_OBJ), NM_IFACE)
            self.nm_props = dbus.Interface(self.bus.get_object(NM_IFACE, NM_OBJ), DBUS_PROP_IFACE)
            self.nm_settings = dbus.Interface(self.bus.get_object(NM_IFACE, NM_SETTINGS_OBJ), NM_SETTINGS_IFACE)
            self.wifi_dev_obj = self.bus.get_object(NM_IFACE, self.nm.GetDeviceByIpIface("wlan0"))
            self.wifi_dev = dbus.Interface(self.wifi_dev_obj, NM_WIFI_DEVICE_IFACE)
            self.wifi_dev_props = dbus.Interface(self.wifi_dev_obj, DBUS_PROP_IFACE)
            self.ap_objs = None
            self.new_conn_obj = None
            self.connectivity = self.nm_props.Get(NM_IFACE, 'Connectivity')
            self.activated = False
            self.activation_status = None
            self.wifi_dev_props.connect_to_signal('PropertiesChanged', self.wifi_dev_props_changed)
            self.nm_props.connect_to_signal('PropertiesChanged', self.nm_props_changed)
            self.nm.connect_to_signal('DeviceAdded', self.nm_device_added)
            self.response_cb = response_cb
            self.api_enabled = True
            self.modem_present = False
            self.modem = None
            self.modem_path = None
            self.modem_sim = None
            self.modem_connman = None
            self.ofono = dbus.Interface(self.bus.get_object(OFONO_BUS_NAME, OFONO_ROOT_PATH), OFONO_MANAGER_IFACE)
            self.ofono.connect_to_signal('ModemAdded', self.modem_added)
        except dbus.DBusException:
            pass

    def get_wlan_hw_address(self):
        return str(self.wifi_dev_props.Get(NM_WIFI_DEVICE_IFACE, 'HwAddress'))

    def find_conn_by_id(self, conn_id):
        conns = self.nm_settings.ListConnections()
        for c_path in conns:
            c = dbus.Interface(self.bus.get_object(NM_IFACE, c_path),
                'org.freedesktop.NetworkManager.Settings.Connection')
            if c.GetSettings()['connection']['id'] == conn_id:
                return c
        return None

    def find_conn_path_by_id(self, conn_id):
        conns = self.nm_settings.ListConnections()
        for c_path in conns:
            c = dbus.Interface(self.bus.get_object(NM_IFACE, c_path),
                'org.freedesktop.NetworkManager.Settings.Connection')
            if c.GetSettings()['connection']['id'] == conn_id:
                return c_path
        return None

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
                ap_props = dbus.Interface(self.bus.get_object(NM_IFACE, ap_obj), DBUS_PROP_IFACE)
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
        return list(ap_dict.values())


    def activate_connection(self, config_data):
        self.activation_status = self.ACTIVATION_PENDING
        try:
            mac = self.get_wlan_hw_address()
            if mac:
                wlan_mac_addr = mac.replace(':', '')

            priority = self.get_highest_priority() + 1
            config_data[CFG_PRIORITY] = priority
            conn = create_wireless_config(wlan_mac_addr, config_data)
            ret, conn = self.add_or_modify_connection(conn)
            if ret:
                self.new_conn_obj = conn
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
                active_conn_props = dbus.Interface(self.bus.get_object(NM_IFACE, active_conn_obj), DBUS_PROP_IFACE)
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

    def nm_device_added(self, dev_path):
        dev_props = dbus.Interface(self.bus.get_object(NM_IFACE, dev_path), DBUS_PROP_IFACE)
        interface = dev_props.Get(NM_DEVICE_IFACE, 'Interface')
        if interface == WWAN_DEV_NAME:
            syslog('Device {} connected.'.format(interface))
            # Request property changes on WWAN interface
            dev_props.connect_to_signal('PropertiesChanged', self.wwan_dev_props_changed)

    def get_activation_status(self):
        return self.activation_status

    def activation_cleanup(self):
        if self.new_conn_obj:
            syslog('Removing connection: {}'.format(self.new_conn_obj))
            conn = dbus.Interface(self.bus.get_object(NM_IFACE, self.new_conn_obj), NM_CONNECTION_IFACE)
            self.new_conn_obj = None
            self.activated = False
            self.activation_status = None

    def stop_scanning(self):
        self.ap_scanning = False

    """
    NOTE: For some reason, using the NetworkManager API to query each
          AP object is very slow, so we process the AP list
          in batches and send them to the client.  Also, reading the APs
          causes the Tx on the BLE GATT characteristic to slow down,
          which leads to long delays (timeouts) for the client.  So,
          the code below implements a callback when the BLE Tx is
          complete.  Thus we only process the AP list after the last
          message was sent, then send the message once we've processed
          the AP list; this ends up being more responsive to the client.
    """
    def ap_scan_tx_complete(self):
        """Callback for AP scan list TX complete
        """
        # Only continue if scanning was not cancelled
        if self.ap_scanning:
            # Schedule call on main loop to process more results
            gobject.timeout_add(0, self.get_ap_cb)

    def get_ap_cb(self):
        """Timer callback to process AP list
        """
        aplist = self.get_access_points(GET_AP_INTERMEDIATE_TIMEOUT, not self.ap_first_scan)
        self.ap_first_scan = False
        # Only continue if scanning was not cancelled
        if self.ap_scanning:
            if aplist and len(aplist) > 0:
                # Send response with TX complete callback to get more
                syslog('Sending intermediate list of {} APs.'.format(len(aplist)))
                self.response_cb(self.AP_SCANNING, data=aplist, tx_complete=self.ap_scan_tx_complete)
            else:
                # Send final response
                syslog('Sending final AP response')
                self.response_cb(self.AP_SCANNING_SUCCESS)
                self.ap_scanning = False
                return False

    def req_get_access_points(self):
        """Handle Get Access Points request
        """
        self.ap_first_scan = True
        self.ap_scanning = True
        # Send response indicating request in progress, with TX complete callback to scan
        self.response_cb(self.AP_SCANNING, tx_complete=self.ap_scan_tx_complete)

    def check_activation(self, cb):
        status = self.get_activation_status()
        if status == self.ACTIVATION_SUCCESS:
            cb(status)
            return False # Exit timer
        elif status == self.ACTIVATION_FAILED_AUTH:
            cb(status)
            self.activation_cleanup()
            return False # Exit timer
        elif status == self.ACTIVATION_FAILED_NETWORK:
            cb(status)
            self.activation_cleanup()
            return False # Exit timer
        if time.time() - self.activation_start_time > ACTIVATION_FAILURE_TIMEOUT:
            # Failed to activate before timeout, send failure and exit timer
            cb(self.ACTIVATION_NO_CONN)
            self.activation_cleanup()
            return False
        elif time.time() - self.activation_msg_time > ACTIVATION_INTERMEDIATE_TIMEOUT:
            # Still waiting for activation, send intermediate response
            cb(self.ACTIVATION_PENDING)
            self.activation_msg_time = time.time()

        return True

    def get_config_from_nm_config(self, nm_config):
        config = {}
        try:
            config['ssid'] = ''.join([chr(b) for b in nm_config['802-11-wireless']['ssid']])
            if 'autoconnect-priority' in nm_config['connection']:
                config['priority'] = int(nm_config['connection']['autoconnect-priority'])
            if '802-11-wireless-security' in nm_config:
                if nm_config['802-11-wireless-security']['key-mgmt'] == 'wpa-eap':
                    config['eap'] = ''.join([str(b) for b in nm_config['802-1x']['eap']])
                    if 'phase2-auth' in nm_config['802-1x']:
                        config['phase2-auth']  = ''.join([str(b) for b in nm_config['802-1x']['phase2-auth']])
            if ('ipv6' in nm_config and
                'ignore-auto-dns' in nm_config['ipv6'] and 'never-default' in nm_config['ipv6'] and
                nm_config['ipv6']['ignore-auto-dns'] and nm_config['ipv6']['never-default']):
                config['disable-ipv6'] = True
            else:
                config['disable-ipv6'] = False
        except KeyError:
            syslog('Invalid nm config')
            return None

        return config

    def req_get_aps(self):
        configs = []
        try:
            conns = self.nm_settings.ListConnections()
            for c_path in conns:
                c = dbus.Interface(self.bus.get_object(NM_IFACE, c_path),
                    'org.freedesktop.NetworkManager.Settings.Connection')
                config = c.GetSettings()
                if config['connection']['type'] == '802-11-wireless':
                    config = self.get_config_from_nm_config(config)
                    if config is not None:
                        configs.append(config)
        except dbus.DBusException:
            return None

        return configs

    def req_connect_ap(self, data):
        """Handle Connect to AP message
        """
        try:
            # Cancel AP scan if in progress
            self.ap_scanning = False
            # Issue request to Network Manager
            if self.activate_connection(data):
                # Config succeeded, connection in progress
                self.response_cb(self.ACTIVATION_PENDING)
                # Set timer task to check connectivity
                self.activation_start_time = time.time()
                self.activation_msg_time = self.activation_start_time
                gobject.timeout_add(ACTIVATION_TIMER_MS, self.check_activation, self.response_cb)
            else:
                # Failed to create connection from configuration
                self.activation_cleanup()
                self.response_cb(self.ACTIVATION_NO_CONN)
        except Exception as e:
            syslog("Failed to connect ap: '%s'" % str(e))

    def get_highest_priority(self):
        priority = 0

        conns = self.nm_settings.ListConnections()
        for c_path in conns:
            c = dbus.Interface(self.bus.get_object(NM_IFACE, c_path),
                NM_CONNECTION_IFACE)
            conn = c.GetSettings()

            if 'autoconnect-priority' in conn['connection']:
                if conn['connection']['autoconnect-priority'] > priority:
                    priority = conn['connection']['autoconnect-priority']

        return priority

    def remove_connection(self,id):
        try:
            conn = self.find_conn_by_id(id)
            if conn != None:
                conn.Delete()
        except dbus.exceptions.DBusException as e:
            syslog('Failed to delete connection: {}'.format(e))
            return False

        return True

    def add_or_modify_connection(self, config):
        try:
            conn = self.find_conn_path_by_id(config[NM_CONNECTION][NM_ID].decode())
            if conn != None:
                conn_iface = dbus.Interface(self.bus.get_object(NM_IFACE, conn),
                'org.freedesktop.NetworkManager.Settings.Connection')
                cur = conn_iface.GetSettings()
                updated = update_wireless_config(cur, config)
                config[NM_CONNECTION][NM_UUID] = cur['connection']['uuid']
                conn_iface.Update(updated)
            else:
                syslog(str(config))
                conn = self.nm_settings.AddConnection(config)
        except dbus.exceptions.DBusException as e:
            syslog('Failed to add or modify connection: {}'.format(e))
            return False, None

        return True, conn

    def req_update_aps(self, config_data):
        mac = self.get_wlan_hw_address()
        if mac:
            wlan_mac_addr = mac.replace(':', '')

        try:
            for config in config_data:
                if CFG_PRIORITY in config and config[CFG_PRIORITY] < 0:
                    if not self.remove_connection(config[CFG_SSID]):
                        return False
                else:
                    conn = create_wireless_config(wlan_mac_addr, config)
                    ret, conn = self.add_or_modify_connection(conn)
                    if not ret:
                        return False
        except KeyError as k:
            syslog('Invalid input configuration: %s' % str(k))
            return False
        except Exception as e:
            syslog('Failed update configs %s' % str(e))
            return False

        return True


    def is_lte_configured(self):
        return self.find_conn_by_id(LTE_CONN_NAME) is not None

    def is_modem_available(self):
        return self.modem_present and self.modem_connman is not None

    def modem_added(self, object_path, properties):
        syslog('Modem added: {}'.format(object_path))
        self.modem_path = object_path
        self.modem = dbus.Interface(self.bus.get_object(OFONO_BUS_NAME,
            self.modem_path), OFONO_MODEM_IFACE)
        self.modem.connect_to_signal('PropertyChanged', self.modem_prop_changed)
        self.modem.SetProperty('Powered', True)

    def modem_prop_changed(self, name, value):
        if name == 'Model' and value == GEMALTO_MODEM_MODEL:
            syslog('{} detected!'.format(GEMALTO_MODEM_MODEL))
            self.modem_present = True
            # If the LTE connection exists, the modem has already been
            # configured, so bring it online
            if self.is_lte_configured():
                syslog('Modem configured, going online.')
                self.modem.SetProperty('Online', True)
                return
        if self.modem_present and name == 'Interfaces':
            if OFONO_SIM_IFACE in value and not self.modem_sim:
                self.modem_sim = dbus.Interface(self.bus.get_object(
                    OFONO_BUS_NAME, self.modem_path), OFONO_SIM_IFACE)
            if OFONO_CONNMAN_IFACE in value and not self.modem_connman:
                self.modem_connman = dbus.Interface(self.bus.get_object(
                    OFONO_BUS_NAME, self.modem_path), OFONO_CONNMAN_IFACE)

    def wwan_dev_props_changed(self, iface, props_changed, props_invalidated):
        """ Signal callback for change to the WWAN device properties
        """
        if props_changed and 'State' in props_changed:
            syslog('WWAN state changed: {}'.format(props_changed['State']))
            if props_changed['State'] == NM_DEVICE_STATE_ACTIVATED:
                syslog('New WWAN connection was activated!')
                self.activated = True
                if self.connectivity == NM_CONNECTIVITY_FULL:
                    self.activation_status = self.ACTIVATION_SUCCESS
            elif props_changed['State'] == NM_DEVICE_STATE_FAILED:
                syslog('New WWAN connection failed.')
                self.activation_status = self.ACTIVATION_FAILED_AUTH

    def req_connect_lte(self, data, cb=None):
        """Handle connectLTE message
        """
        if not cb:
            cb = self.response_cb
        if not self.is_modem_available():
            syslog('No modem available!')
            cb(self.ACTIVATION_INVALID)
            return
        if self.modem_sim is None or not self.modem_sim.GetProperties()['Present']:
            syslog('No SIM present!')
            cb(self.ACTIVATION_NO_SIM)
            return
        syslog('Configuring LTE connection.')
        apn = data.get('apn')
        username = data.get('username')
        password = data.get('password')
        self.activation_status = self.ACTIVATION_PENDING
        cb(self.activation_status)
        try:
            # Create auto-connection for WWAN Ethernet device
            conn = create_lte_conn(LTE_CONN_NAME, WWAN_DEV_NAME)
            self.new_conn_obj = self.nm_settings.AddConnection(conn)
            # Configure the connection (if not default)
            if apn or username or password:
                ctxs = self.modem_connman.GetContexts()
                default_ctx = dbus.Interface(self.bus.get_object(
                    OFONO_BUS_NAME, ctxs[0][0]), OFONO_CONNECTION_IFACE)
                if apn:
                    syslog('Configuring LTE connection for APN: '.format(apn))
                    default_ctx.SetProperty('AccessPointName', apn)
                if username:
                    default_ctx.SetProperty('Username', username)
                if password:
                    default_ctx.SetProperty('Password', password)
            # Set the modem online
            syslog('Attempting to bring up LTE connection.')
            self.modem.SetProperty('Online', True)
            # Set timer to check on activation
            self.activation_start_time = time.time()
            self.activation_msg_time = self.activation_start_time
            gobject.timeout_add(ACTIVATION_TIMER_MS, self.check_activation, cb)
        except dbus.exceptions.DBusException as e:
            syslog('Failed to create connection: {}'.format(e))
            cb(self.ACTIVATION_INVALID)

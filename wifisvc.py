"""
Gatt server implementation for configuration the Wi-Fi interface over BLE
"""
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import uuid
import array
import time
import gattsvc

from syslog import syslog, openlog

try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject
import sys

IG_DEFAULT_CON =      'IG-CONN'
NM_IFACE =            'org.freedesktop.NetworkManager'
NM_SETTINGS_IFACE =   'org.freedesktop.NetworkManager.Settings'
NM_SETTINGS_OBJ =     '/org/freedesktop/NetworkManager/Settings'
NM_OBJ =              '/org/freedesktop/NetworkManager'
NM_CONNECTION_IFACE = 'org.freedesktop.NetworkManager.Settings.Connection'
NM_DEVICE_IFACE =     'org.freedesktop.NetworkManager.Device'
DBUS_PROP_IFACE =     'org.freedesktop.DBus.Properties'

UUID_WIFI_SVC =         'f365403e-f94b-4982-9087-716916d90d42'
UUID_WIFI_SSID =        '2fe0f5dc-3cdc-4602-ae92-7c8d3495b945'
UUID_WIFI_KEY_MGMT =    'e95962db-0584-4d6b-80c6-264660e1a717'
UUID_WIFI_PSK =         'c487dfd9-b9f8-423f-a9d8-e8ac70c67e3d'
UUID_WIFI_AUTH_ALG =    '52c187a1-910a-45f3-8cb4-d2a1511ccf5d'
UUID_WIFI_LEAP_USER =   '15280d6d-fa10-411f-880f-f806f296ec4e'
UUID_WIFI_LEAP_PASS =   '748eda5d-af17-41ac-817b-45afea0d5a1e'
UUID_WIFI_WEP_KEY1 =    'ef9be1f4-1d2d-4ab1-b6a5-06bfec24cbd7'
UUID_WIFI_WEP_KEY2 =    '55ae79f2-7ab9-4c44-a70c-13e44dd2036d'
UUID_WIFI_WEP_KEY3 =    '9a226b3c-8a79-47aa-8b4e-dfb767a2eb5c'
UUID_WIFI_WEP_KEY4 =    '31508b3e-82d2-41d9-8c45-f1490c75a734'
UUID_WIFI_EAP =         '23692fc1-32eb-4e86-a160-d0b0ab2df166'
UUID_WIFI_IDENTITY =    '51ecf5a2-716e-4463-9153-49d6f95f9c21'
UUID_WIFI_PASS =        '9b77be4b-386e-4fac-a565-72a51439710d'
UUID_WIFI_PHASE2_AUTH = '3efae3bb-1274-4a03-9df8-0dd00422c09f'
UUID_WIFI_CA_CERT =     '8f2a588a-42d3-4401-8432-b4b80163a14c'
UUID_WIFI_CLIENT_CERT = 'd248c665-6b55-4280-b1de-65730c3983bd'
UUID_WIFI_PRIVATE_KEY = 'cdd9ea6d-3c5b-4b82-8e7a-6d46f4e86b48'
UUID_WIFI_KEY_PASS    = '037ef2e1-b922-49cb-9908-c2f5d2664776'
UUID_WIFI_ACTIVATE    = '94734160-5fd2-4dc2-8a22-ed3a65bd65aa'
UUID_WIFI_STATE       = '602fc23c-4d68-4d90-a4b8-1e0aa0531508'

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
NM_DEVICE_STATE_ACTIVATED = 110
NM_DEVICE_STATE_FAILED = 120

info = dbus.Dictionary({
    'type': '802-11-wireless',
    'id': IG_DEFAULT_CON,
    'autoconnect': False,
    'interface-name': 'wlan0'})

wireless = dbus.Dictionary({
    'mode': 'infrastructure',
    'ssid': ''
})

con = dbus.Dictionary({
    'connection': info,
    '802-11-wireless': wireless
})

class WifiConfigService(gattsvc.Service):
    """
    Contains the Wi-Fi configuration and activation characteristics
    """
    def __init__(self, bus, index):
        gattsvc.Service.__init__(self, bus, index, UUID_WIFI_SVC, True)
        self.add_characteristic(WifiConfigBytesCharacteristic(bus, 0, self,
                                                              UUID_WIFI_SSID,
                                                              '802-11-wireless',
                                                              'ssid'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 1, self,
                                                               UUID_WIFI_KEY_MGMT,
                                                               '802-11-wireless-security',
                                                               'key-mgmt'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 2, self,
                                                               UUID_WIFI_PSK,
                                                               '802-11-wireless-security',
                                                               'psk'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 3, self,
                                                               UUID_WIFI_AUTH_ALG,
                                                               '802-11-wireless-security',
                                                               'auth-alg'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 4, self,
                                                               UUID_WIFI_LEAP_USER,
                                                               '802-11-wireless-security',
                                                               'leap-username'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 5, self,
                                                               UUID_WIFI_WEP_KEY1,
                                                               '802-11-wireless-security',
                                                               'wep-key1'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 6, self,
                                                               UUID_WIFI_WEP_KEY2,
                                                               '802-11-wireless-security',
                                                               'wep-key2'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 7, self,
                                                               UUID_WIFI_WEP_KEY3,
                                                               '802-11-wireless-security',
                                                               'wep-key3'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 8, self,
                                                               UUID_WIFI_WEP_KEY4,
                                                               '802-11-wireless-security',
                                                               'wep-key4'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 9, self,
                                                               UUID_WIFI_LEAP_PASS,
                                                               '802-11-wireless-security',
                                                               'leap-password'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 10, self,
                                                               UUID_WIFI_EAP,
                                                               '802-1x',
                                                               'eap'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 11, self,
                                                               UUID_WIFI_IDENTITY,
                                                               '802-1x',
                                                               'identity'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 12, self,
                                                               UUID_WIFI_PASS,
                                                               '802-1x',
                                                               'password'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 13, self,
                                                               UUID_WIFI_PHASE2_AUTH,
                                                               '802-1x',
                                                               'phase2-auth'))

        self.add_characteristic(WifiConfigBytesCharacteristic(bus, 14, self,
                                                              UUID_WIFI_CA_CERT,
                                                              '802-1x',
                                                              'ca-cert'))

        self.add_characteristic(WifiConfigBytesCharacteristic(bus, 15, self,
                                                              UUID_WIFI_CLIENT_CERT,
                                                              '802-1x',
                                                              'client-cert'))

        self.add_characteristic(WifiConfigBytesCharacteristic(bus, 16, self,
                                                              UUID_WIFI_PRIVATE_KEY,
                                                              '802-1x',
                                                              'private-key'))

        self.add_characteristic(WifiConfigStringCharacteristic(bus, 17, self,
                                                               UUID_WIFI_KEY_PASS,
                                                               '802-1x',
                                                               'private-key-passord'))

        self.add_characteristic(WifiActivateConfigCharacteristic(bus, 18, self))
        self.add_characteristic(WifiStateCharacteristic(bus, 19, self))


class WifiConfigBytesCharacteristic(gattsvc.Characteristic):
    """
    Write one of the Wi-Fi configuration parameters
    """
    def __init__(self, bus, index, service, uuid, setting, prop):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            uuid,
            ['read', 'write'],
            service)
        self.value = b''
        self.setting = setting
        self.prop = prop
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = value
        if self.setting not in con:
            con[self.setting] = {}
        con[self.setting][self.prop] = self.value

class WifiConfigStringCharacteristic(gattsvc.Characteristic):
    """
    Write one of the Wi-Fi configuration parameters
    """
    def __init__(self, bus, index, service, uuid, setting, prop):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            uuid,
            ['read', 'write'],
            service)
        self.value = ''
        self.setting = setting
        self.prop = prop
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        if self.setting not in con:
            con[self.setting] = {}
        con[self.setting][self.prop] = self.value

class WifiActivateConfigCharacteristic(gattsvc.Characteristic):
    """
    Activates the current Wi-Fi configuration
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_WIFI_ACTIVATE,
            ['read','write'],
            service)
        self.value = b''
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        delete_connection(IG_DEFAULT_CON)
        bus = dbus.SystemBus()
        proxy = bus.get_object(NM_IFACE, NM_OBJ)
        nm = dbus.Interface(proxy, NM_IFACE)
        devpath = nm.GetDeviceByIpIface('wlan0')
        nm.AddAndActivateConnection(con,devpath,'/')
        syslog('Connection activated')


class WifiStateCharacteristic(gattsvc.Characteristic):
    """
    Notify the client of Wi-Fi state changes.
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_WIFI_STATE,
            ['read', 'notify'],
            service)
        self.notifying = False
        self.state = None
        self.connect_signals()

    def connect_signals(self):
        try:
            bus = dbus.SystemBus()

            proxy = bus.get_object(NM_IFACE, NM_OBJ)
            manager = dbus.Interface(proxy, NM_IFACE)

            devices = manager.GetDevices()
            for d in devices:
                dev_proxy = bus.get_object(NM_IFACE, d)
                prop_iface = dbus.Interface(dev_proxy, DBUS_PROP_IFACE)

                name = prop_iface.Get(NM_DEVICE_IFACE, "Interface")

                if name == "wlan0":
                    state_signal = dev_proxy.connect_to_signal('StateChanged', self.state_changed)
                    return

            syslog('Cannot connect signals.  Unable to find the wlan0 interface')
        except dbus.exceptions.DBusException as e:
            syslog("Failed to initialize D-Bus object: '%s'" % str(e))
            sys.exit(1)

    def state_changed(self, new_state, old_state, reason):
        self.state = new_state
        if not self.notifying:
            return
        self.PropertiesChanged(
            gattsvc.GATT_CHRC_IFACE,
            { 'Value': [dbus.Byte(self.state)] }, [])

    def ReadValue(self, options):
        return [dbus.Byte(self.state)]

    def StartNotify(self):
        if self.notifying:
            return

        self.notifying = True

    def StopNotify(self):
        if not self.notifying:
            return

        self.notifying = False

def delete_connection(id):
    bus = dbus.SystemBus()
    nm = bus.get_object(NM_IFACE, NM_SETTINGS_OBJ)
    nm_settings = dbus.Interface(nm, NM_SETTINGS_IFACE)

    for path in nm_settings.ListConnections():
        connection_proxy = bus.get_object(NM_IFACE, path)
        connection = dbus.Interface(connection_proxy, NM_CONNECTION_IFACE)
        connection_settings = connection.GetSettings()
        if connection_settings['connection']['id'] == id:
            connection.Delete()
"""
Gatt server implementation for configuration the provisioning server over BLE
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

IG_PROV_IFACE = 'com.lairdtech.IG.ProvService'
IG_PROV_OBJ = '/com/lairdtech/IG/ProvService'

UUID_CONF_SVC =         '3f2246fa-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_ENDPOINT =    '3f224f42-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_CERT =        '3f2252d0-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_USER =        '3f22594c-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_PASSWORD =    '3f2256b8-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_STATE =       '3f225e4c-449d-11e8-842f-0ed5f89f718b'
UUID_CONF_START_PROV =  '3f2260e0-449d-11e8-842f-0ed5f89f718b'

config_service = None
auth_params = {}
endpoint_url = None

class ConfService(gattsvc.Service):
    """
    Contains the IG provisioning configuration and activation characteristics
    """

    def __init__(self, bus, index):
        gattsvc.Service.__init__(self, bus, index, UUID_CONF_SVC, True)

        bus = dbus.SystemBus()
        config_service = bus.get_object(IG_PROV_IFACE, IG_PROV_OBJ)

        self.add_characteristic(ConfEndpointCharacteristic(bus, 0, self))
        self.add_characteristic(ConfCertificateCharacteristic(bus, 1, self))
        self.add_characteristic(ConfUserCharacteristic(bus, 2, self))
        self.add_characteristic(ConfPasswordCharacteristic(bus, 3, self))
        self.add_characteristic(ConfStartProvisioningCharacteristic(bus, 4, self))
        self.add_characteristic(ConfStateCharacteristic(bus, 5, self))


class ConfEndpointCharacteristic(gattsvc.Characteristic):
    """
    Write the cloud endpoint configuration parameter
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_ENDPOINT,
            ['read', 'write'],
            service)
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        endpoint_url = self.value


class ConfCertificateCharacteristic(gattsvc.Characteristic):
    """
    Write the certificate configuration parameter
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_CERT,
            ['read', 'write'],
            service)

        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        with open('/tmp/%s' % self.value, "r") as f:
            auth_params['clientcert'] = f.read()


class ConfUserCharacteristic(gattsvc.Characteristic):
    """
    Write the username configuration parameter
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_USER,
            ['read', 'write'],
            service)
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        auth_params['username'] = self.value


class ConfPasswordCharacteristic(gattsvc.Characteristic):
    """
    Write the password configuration parameter
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_PASSWORD,
            ['read', 'write'],
            service)

        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        auth_params['password'] = self.value


class ConfStartProvisioningCharacteristic(gattsvc.Characteristic):
    """
    Start the provisioning process
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_START_PROV,
            ['read', 'write'],
            service)

        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = ''.join([chr(byte) for byte in value])
        config_service.StartProvisioning(endpoint_url, auth_params)


class ConfStateCharacteristic(gattsvc.Characteristic):
    """
    Notify the client of a provisioning state change
    """

    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_CONF_STATE,
            ['notify'],
            service)
        self.notifying = False
        self.state = None
        self.connect_signals()

    def connect_signals(self):
        try:
            bus = dbus.SystemBus()
            proxy = bus.get_object(IG_PROV_IFACE, IG_PROV_OBJ)
            proxy.connect_to_signal('StateChanged', self.state_changed)
        except dbus.exceptions.DBusException as e:
            syslog("Failed to initialize D-Bus object: '%s'" % str(e))
            sys.exit(1)

    def state_changed(self, result):
        self.state = result

        if not self.notifying:
            return

        self.PropertiesChanged(
            gattsvc.GATT_CHRC_IFACE,
            {'Value': [dbus.Byte(self.state)]}, [])

    def StartNotify(self):
        if self.notifying:
            return

        self.notifying = True

    def StopNotify(self):
        if not self.notifying:
            return

        self.notifying = False

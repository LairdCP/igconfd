"""
LE advertising implementation for IG configuration service
"""
import dbus, dbus.exceptions, dbus.types, dbus.service
import dbus.mainloop.glib

DBUS_PROP_IFACE =      'org.freedesktop.DBus.Properties'
LE_ADVERT_DATA_IFACE = 'org.bluez.LEAdvertisement1'

class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

class LEAdvertData(dbus.service.Object):
    """
    org.bluez.LEAdvertisement1 interface implementation
    """
    PATH_BASE = '/org/bluez/gatt/leadvertdata'

    def __init__(self, bus, index, service_uuids, device_name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.service_uuids = service_uuids
        self.device_name = device_name
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
                LE_ADVERT_DATA_IFACE: {
						'ServiceUUIDs': self.service_uuids,
                        'Type': 'peripheral',
                        'LocalName': self.device_name
                }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE,
                         in_signature='s',
                         out_signature='a{sv}')
    def GetAll(self, interface):
        if interface != LE_ADVERT_DATA_IFACE:
            raise InvalidArgsException()
        return self.get_properties()[LE_ADVERT_DATA_IFACE]

    @dbus.service.method(LE_ADVERT_DATA_IFACE)
    def Release(self, options):
        pass

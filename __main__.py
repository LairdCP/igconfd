import os
import dbus, dbus.service, dbus.exceptions
import sys, signal
from syslog import syslog, openlog
from dbus.mainloop.glib import DBusGMainLoop
import systemd
import systemd.daemon
import wifisvc
import filesvc
import confsvc

try:
  from gi.repository import GObject
except ImportError:
  import gobject as GObject

DBUS_OM_IFACE =       'org.freedesktop.DBus.ObjectManager'
BLUEZ_SERVICE_NAME =  'org.bluez'
GATT_MANAGER_IFACE =  'org.bluez.GattManager1'

class Application(dbus.service.Object):
    """
    org.bluez.GattApplication1 interface implementation
    """
    def __init__(self, bus):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        con_list = [dict() for x in range(10)]
        self.add_service(wifisvc.WifiConfigService(bus, 0))
        self.add_service(filesvc.FileTransferService(bus, 1))
        self.add_service(confsvc.ConfService(bus, 2))

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature='a{oa{sa{sv}}}')
    def GetManagedObjects(self):
        response = {}

        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
                descs = chrc.get_descriptors()
                for desc in descs:
                    response[desc.get_path()] = desc.get_properties()

        return response

def register_app_cb():
    syslog('GATT application registered')


def register_app_error_cb(error):
    syslog('Failed to register application: ' + str(error))
    mainloop.quit()


def find_adapter(bus):
    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, '/'),
                               DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    for o, props in objects.items():
        if GATT_MANAGER_IFACE in props.keys():
            return o

    return None

def main():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    bus = dbus.SystemBus()

    adapter = find_adapter(bus)
    if not adapter:
        syslog('GattManager1 interface not found')
        return

    service_manager = dbus.Interface(
            bus.get_object(BLUEZ_SERVICE_NAME, adapter),
            GATT_MANAGER_IFACE)

    app = Application(bus)

    mainloop = GObject.MainLoop()

    syslog('Registering GATT application...')

    service_manager.RegisterApplication(app.get_path(), {},
                                    reply_handler=register_app_cb,
                                    error_handler=register_app_error_cb)
    # Notify systemd now that BLE profiles are registered
    systemd.daemon.notify('READY=1')
    mainloop.run()


#
# Run the main loop
#
openlog("IG.ConfService")
syslog("Starting main loop.")
main()


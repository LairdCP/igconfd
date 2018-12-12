"""
devmngr - BLE Device Manager functionality for the BLE configuration service
"""

import dbus, dbus.service, dbus.exceptions
import json
import subprocess
import leadvert
import vspsvc
from messagemngr import MessageManager
from netmngr import NetManager
from syslog import syslog

try:
  from gi.repository import GObject
except ImportError:
  import gobject as GObject

DBUS_OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
BLUEZ_SERVICE_NAME = 'org.bluez'
GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
ADAPTER_IFACE = 'org.bluez.Adapter1'
BLUEZ_DEVICE_IFACE = 'org.bluez.Device1'
LE_ADVERT_MGR_IFACE = 'org.bluez.LEAdvertisingManager1'
DEVICE_SVC_NAME = 'com.lairdtech.device.DeviceService'
DEVICE_SVC_PATH = '/com/lairdtech/device/DeviceService'
DEVICE_IFACE = 'com.lairdtech.device.DeviceInterface'

BLE_STATE_ACTIVE = 1
BLE_STATE_INACTIVE = 0

class Application(dbus.service.Object):
    """
    org.bluez.GattApplication1 interface implementation
    """
    def __init__(self, bus, msg_manager):
        self.path = '/'
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)
        self.vsp_svc = vspsvc.VirtualSerialPortService(bus, 0, self.rx_cb)
        self.add_service(self.vsp_svc)
        self.rx_timeout_id = None
        self.rx_message = None
        syslog('Starting message manager.')
        self.msg_manager = msg_manager
        self.msg_manager.start(self.vsp_svc.tx)

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

    def rx_timeout(self):
        syslog('Timeout while receiving JSON message.')
        self.rx_message = None
        self.rx_timeout_id = None
        return False

    def rx_cb(self, message):
         self.rx_message = (self.rx_message or '') + message
         if self.rx_timeout_id:
             GObject.source_remove(self.rx_timeout_id)
             self.rx_timeout_id = None
         try:
             req_obj = json.loads(self.rx_message)
             syslog('JSON request decoded.')
             self.msg_manager.add_request(req_obj)
             self.rx_message = None
         except ValueError:
             self.rx_timeout_id = GObject.timeout_add(2000, self.rx_timeout_cb)

class DeviceManager():
    def __init__(self):
        self.bus = dbus.SystemBus()
        self.net_manager = NetManager()
        self.msg_manager = MessageManager(self.net_manager, self.stop)
        self.adapter = self.find_obj_by_iface(GATT_MANAGER_IFACE)
        self.gatt_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME,
            self.adapter), GATT_MANAGER_IFACE)
        self.advert_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME,
            self.adapter), LE_ADVERT_MGR_IFACE)
        wlan_mac_addr = self.net_manager.get_wlan_hw_address()
        device_name = 'Laird IG60 ({})'.format(wlan_mac_addr[-8:])
        self.le_adv_data = leadvert.LEAdvertData(self.bus, 0, [vspsvc.UUID_VSP_SVC],
            device_name)
        self.vsp_app = Application(self.bus, self.msg_manager)
        self.device_svc = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
            DEVICE_SVC_PATH), DEVICE_IFACE)

    def find_objs_by_iface(self, iface):
        found_objs = []
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, '/'),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        for o, props in objects.items():
            if iface in props.keys():
                found_objs.append(o)
        return found_objs

    def find_obj_by_iface(self, iface):
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, '/'),
            DBUS_OM_IFACE)
        objects = remote_om.GetManagedObjects()
        for o, props in objects.items():
            if iface in props.keys():
                return o
        return None

    def register_app_cb(self):
        syslog('GATT application registered')

    def register_app_error_cb(self, error):
        syslog('Failed to register application: ' + str(error))

    def register_ad_cb(self):
        syslog('LE Advertisement registered.')

    def register_ad_error_cb(self, error):
        syslog('Failed to register LE advertisement: ' + str(error))

    def disconnect_devices(self):
        device_objs = self.find_objs_by_iface(BLUEZ_DEVICE_IFACE)
        if device_objs:
            for d in device_objs:
                syslog('Found device: {}'.format(d))
                dev = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME,
                    d), BLUEZ_DEVICE_IFACE)
                dev_props = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME,
                    d), DBUS_PROP_IFACE)
                if dev_props.Get(BLUEZ_DEVICE_IFACE, 'Connected'):
                    syslog('Disconnecting device {}'.format(dev_props.Get(BLUEZ_DEVICE_IFACE, 'Address')))
                    dev.Disconnect()

    def start_provisioning_service(self):
        self.device_svc.SetBLEState(BLE_STATE_ACTIVE)
        syslog('Registering GATT application...')
        self.gatt_manager.RegisterApplication(self.vsp_app.get_path(), {},
            reply_handler=self.register_app_cb,
            error_handler=self.register_app_error_cb)
        syslog('Registering LE Advertisement Data...')
        self.advert_manager.RegisterAdvertisement(self.le_adv_data.get_path(), {},
            reply_handler=self.register_ad_cb,
            error_handler=self.register_ad_error_cb)
        syslog('Enabling pairing via SSP.')
        subprocess.call(['btmgmt', 'ssp', 'on'])

    def stop_provisioning_service(self):
        self.disconnect_devices()
        self.device_svc.SetBLEState(BLE_STATE_INACTIVE)
        syslog('Disabling pairing via SSP.')
        subprocess.call(['btmgmt', 'ssp', 'off'])
        syslog('Unregistering LE Advertisement Data...')
        self.advert_manager.UnregisterAdvertisement(self.le_adv_data.get_path())
        syslog('Unregistering GATT application...')
        self.gatt_manager.UnregisterApplication(self.vsp_app.get_path())

    def start(self):
        if self.msg_manager.is_provisioned():
            syslog('Device is provisioned, skipping BLE service.')
        else:
            syslog('Device is not provisioned, starting BLE service...')
            self.start_provisioning_service()

    def stop(self):
        # Stop after a delay to allow last status message to be sent
        GObject.timeout_add(2000, self.stop_provisioning_service)

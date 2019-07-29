"""
The CustomService will extend the the ConfigurationService to implement
the features specific to the IG60. 
"""

import dbus, dbus.service, dbus.exceptions
import json
import os, os.path
import time
import subprocess

from syslog import syslog
from configsvc import ConfigurationService

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject

# DBus paths for the IG services
DEVICE_SVC_NAME = 'com.lairdtech.device.DeviceService'
DEVICE_SVC_PATH = '/com/lairdtech/device/DeviceService'
DEVICE_IFACE = 'com.lairdtech.device.DeviceInterface'
PROV_SVC = 'com.lairdtech.IG.ProvService'
PROV_IFACE = 'com.lairdtech.IG.ProvInterface'
PROV_OBJ = '/com/lairdtech/IG/ProvService'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

PROV_COMPLETE_SUCCESS = 0
BUTTON_PRESS_SHORT = 0

BLE_STATE_ACTIVE = 1
BLE_STATE_INACTIVE = 0

class CustomService(ConfigurationService):
    def __init__(self, device):

        ConfigurationService.__init__(self, device)

        try:
            self.device_svc = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
            DEVICE_SVC_PATH), DEVICE_IFACE)
            self.device_svc.connect_to_signal('ConfigButtonPress', self.config_button_press)
        
            self.prov = dbus.Interface(self.bus.get_object(PROV_SVC, PROV_OBJ), PROV_IFACE)
            self.prov_props = dbus.Interface(self.bus.get_object(PROV_SVC, PROV_OBJ), DBUS_PROP_IFACE)
            self.prov.connect_to_signal('StateChanged', self.prov_state_changed)
            self.prov_state = self.prov_props.Get(PROV_IFACE, 'Status')
  
        except dbus.DBusException:
            exit

    def enable_ble_service(self):
        syslog('Enabling BLE service.')
        self.device_svc.SetBLEState(BLE_STATE_ACTIVE)
        subprocess.call(['btmgmt', 'power', 'on'])

    def disable_ble_service(self):
        syslog('Disabling BLE service.')
        self.disconnect_devices()
        self.device_svc.SetBLEState(BLE_STATE_INACTIVE)
        subprocess.call(['btmgmt', 'power', 'off'])
        return False

    def start(self):
        if self.prov_state == PROV_COMPLETE_SUCCESS:
            syslog('Device is provisioned, skipping BLE service.')
        else:
            syslog('Device is not provisioned, starting BLE service...')
            self.enable_ble_service()

    def stop(self):
        # Stop after a delay to allow last status message to be sent
        gobject.timeout_add(2000, self.disable_ble_service)

    def prov_state_changed(self, state):
        if state == PROV_COMPLETE_SUCCESS:
            self.stop()

    def config_button_press(self, press_type):
        # If button is pressed (short) and already provisioned, enable service
        if press_type == BUTTON_PRESS_SHORT and self.prov_state == PROV_COMPLETE_SUCCESS:
            syslog('Config button pressed, enabling BLE service.')
            self.enable_ble_service()
"""
The ConfigurationService will initialize the Gatt application that does the BLE
work.  
"""

import dbus, dbus.service, dbus.exceptions
import json
import os, os.path
import time
import subprocess
import leadvert
import vspsvc

from app import Application
from messagemngr import MessageManager
from syslog import syslog

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject

class ConfigurationService(Application):
    def __init__(self, device):
        self.bus = dbus.SystemBus()
        self.msg_manager = MessageManager(self.stop)
        self.device = device
        wlan_mac_addr = self.msg_manager.net_manager.get_wlan_hw_address()
        self.device_name = 'Laird {} ({})'.format(device, wlan_mac_addr[-8:])

        Application.__init__(self, self.bus, self.device_name)

        self.msg_manager.start(self.vsp_svc.tx)
        self.init_ble_service()   

    def start(self):
        syslog('Enabling BLE service.')
        subprocess.call(['btmgmt', 'power', 'on'])

    def stop(self):
        syslog('Disabling BLE service.')
        self.disconnect_devices()
        subprocess.call(['btmgmt', 'power', 'off'])
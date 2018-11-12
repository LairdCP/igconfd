"""
provmngr - Provisioning functionality for the BLE configuration service
"""

import dbus, dbus.exceptions
from syslog import syslog

PROV_SVC = 'com.lairdtech.IG.ProvService'
PROV_IFACE = 'com.lairdtech.IG.ProvInterface'
PROV_OBJ = '/com/lairdtech/IG/ProvService'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

class ProvManager():
    """Provisioning States - these must match the IG Provisioning Service
    """
    PROV_COMPLETE_SUCCESS = 0
    PROV_UNPROVISIONED = 1
    PROV_INPROGRESS_DOWNLOADING = 2
    PROV_INPROGRESS_APPLYING = 3
    PROV_FAILED_INVALID = -1
    PROV_FAILED_CONNECT = -2
    PROV_FAILED_AUTH = -3
    PROV_FAILED_TIMEOUT = -4
    PROV_FAILED_NOT_FOUND = -5

    def __init__(self):
        bus = dbus.SystemBus()
        self.prov = dbus.Interface(bus.get_object(PROV_SVC, PROV_OBJ), PROV_IFACE)
        self.prov_props = dbus.Interface(bus.get_object(PROV_SVC, PROV_OBJ), DBUS_PROP_IFACE)
        self.prov.connect_to_signal('StateChanged', self.prov_state_changed)
        self._prov_state = self.prov_props.Get(PROV_IFACE, 'Status')

    def prov_state_changed(self, state):
        syslog('Provisioning state changed: {}'.format(state))
        self._prov_state = state

    def get_prov_state(self):
        return self._prov_state

    def start_provisioning(self, prov_data):
        syslog('Starting provisioning.')
        try:
            return self.prov.StartProvisioning(prov_data['url'],
                { 'username' : prov_data['username'],
                  'password' : prov_data['password'] } )
        except KeyError:
            syslog('Invalid provisioning request data.')
            return self.PROV_FAILED_INVALID

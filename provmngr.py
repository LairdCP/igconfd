"""
provmngr - Provisioning functionality for the BLE configuration service
"""

import time
import dbus, dbus.exceptions
from syslog import syslog

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject

PROV_SVC = 'com.lairdtech.IG.ProvService'
PROV_IFACE = 'com.lairdtech.IG.ProvInterface'
PROV_OBJ = '/com/lairdtech/IG/ProvService'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

PROVISION_INTERMEDIATE_TIMEOUT = 2
PROVISION_TIMER_MS = 500

EDGEIQ_URL = 'http://api.edgeiq.io/'

class ProvManager():
    """
    Provisioning States - these must match the IG Provisioning Service
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
    PROV_FAILED_BAD_CONFIG = -6

    def __init__(self, response_cb):
        self._prov_state = self.PROV_UNPROVISIONED
        try:
            bus = dbus.SystemBus()
            self.prov = dbus.Interface(bus.get_object(PROV_SVC, PROV_OBJ), PROV_IFACE)
            self.prov_props = dbus.Interface(bus.get_object(PROV_SVC, PROV_OBJ), DBUS_PROP_IFACE)
            self.prov.connect_to_signal('StateChanged', self.prov_state_changed)
            self._prov_state = self.prov_props.Get(PROV_IFACE, 'Status')
            self._greengrass_prov_state = self.prov_props.Get(PROV_IFACE, 'GreengrassProvisioned')
            self._edgeiq_prov_state = self.prov_props.Get(PROV_IFACE, 'EdgeIQProvisioned')
            self.response_cb = response_cb

            # Disabled the API if provisioning is complete or there is no Provisioning Service
            if self._prov_state == self.PROV_COMPLETE_SUCCESS and \
                self._greengrass_prov_state == True:
                self.api_enabled = False
            else:
                self.api_enabled = True
        except dbus.DBusException:
            self.api_enabled = False

    def is_provisioned(self):
        return self._prov_state == self.PROV_COMPLETE_SUCCESS and \
                self._greengrass_prov_state == True

    def disable_api(self):
        self.api_enabled = False

    def prov_state_changed(self, state):
        syslog('Provisioning state changed: {}'.format(state))
        self._prov_state = state
        self._greengrass_prov_state = self.prov_props.Get(PROV_IFACE, 'GreengrassProvisioned')
        self._edgeiq_prov_state = self.prov_props.Get(PROV_IFACE, 'EdgeIQProvisioned')

    def get_prov_state(self):
        return self._prov_state

    def get_greengrass_prov_state(self):
        return self._greengrass_prov_state

    def get_edgeiq_prov_state(self):
        return self._edgeiq_prov_state

    def is_provisioning(self):
        if self._prov_state == self.PROV_UNPROVISIONED or \
            self._prov_state == self.PROV_INPROGRESS_DOWNLOADING or \
            self._prov_state == self.PROV_INPROGRESS_APPLYING:
            return True
        else:
            return False

    def check_provision(self):
        ret = self.is_provisioning()
        if ret and time.time() - self.provision_msg_time > PROVISION_INTERMEDIATE_TIMEOUT:
            # Still waiting for completion, send intermediate response
            self.provision_msg_time = time.time()
            if self._prov_state == self.PROV_INPROGRESS_DOWNLOADING:
                data = {'operation' : 'download'}
            elif self._prov_state == self.PROV_INPROGRESS_APPLYING:
                data = {'operation' : 'apply'}
            else:
                data = None

            self.response_cb(self._prov_state, data)
        elif not ret:
            self.response_cb(self._prov_state)

        return ret

    def start_provisioning(self, prov_data):

        syslog('Starting provisioning.')
        if self._prov_state == self.PROV_INPROGRESS_DOWNLOADING or \
            self._prov_state == self.PROV_INPROGRESS_APPLYING:
            return
        try:
            if 'username' in prov_data and 'password' in prov_data:
                auth_params = { 'username' : prov_data['username'].encode(),
                  'password' : prov_data['password'].encode() }
            else:
                auth_params = {}
            status = self.prov.StartProvisioning(prov_data['url'].encode(),
                 auth_params)
            self.response_cb(status)
            self._prov_state = status
        except KeyError:
            syslog('Invalid provisioning request data.')
            self.response_cb(self.PROV_FAILED_INVALID)
            self._prov_state = self.PROV_FAILED_INVALID
            return

        if self.is_provisioning():
            # Success, send actualt response
            self.response_cb(self.PROV_UNPROVISIONED, {'operation' : 'connect'})
            # Set timer task to check status & sent intermediate responses
            self.provision_msg_time = time.time()
            gobject.timeout_add(PROVISION_TIMER_MS, self.check_provision)
        else:
            self.response_cb(self.PROV_FAILED_CONNECT)

    def start_provisioning_edge(self, prov_data):
        syslog('Starting provisioning Edge.')
        if self._prov_state == self.PROV_INPROGRESS_DOWNLOADING or \
            self._prov_state == self.PROV_INPROGRESS_APPLYING:
            return
        try:
            # Construct special EdgeIQ "url"
            url = EDGEIQ_URL + prov_data['company']
            status = self.prov.StartProvisioning(url.encode(), {})
            self.response_cb(status)
            self._prov_state = status
        except KeyError:
            syslog('Invalid provisioning request data.')
            self.response_cb(self.PROV_FAILED_INVALID)
            self._prov_state = self.PROV_FAILED_INVALID
            return

        if self.is_provisioning():
            # Success, send actualt response
            self.response_cb(self.PROV_UNPROVISIONED, {'operation' : 'connect'})
            # Set timer task to check status & sent intermediate responses
            self.provision_msg_time = time.time()
            gobject.timeout_add(PROVISION_TIMER_MS, self.check_provision)
        else:
            self.response_cb(self.PROV_FAILED_CONNECT)

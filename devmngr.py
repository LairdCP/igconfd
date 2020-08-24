"""
devmngr - Device service functionality for the BLE configuration service
"""

import dbus, dbus.exceptions
from syslog import syslog
import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject

"""
Status codes for MessageManager responses
"""
MSG_STATUS_INTERMEDIATE = 1
MSG_STATUS_SUCCESS = 0
MSG_STATUS_ERR_INVALID = -1
MSG_STATUS_ERR_TIMEOUT = -2
MSG_STATUS_ERR_AUTH = -3
MSG_STATUS_ERR_NOTFOUND = -4
MSG_STATUS_ERR_NOCONN = -5
MSG_STATUS_ERR_DEVICE = -6
MSG_STATUS_API_DISABLED = -7

"""
DBUS paths for the DeviceService
"""
DEVICE_SVC_NAME = 'com.lairdtech.device.DeviceService'
DEVICE_SVC_PATH = '/com/lairdtech/device/DeviceService'
DEVICE_IFACE = 'com.lairdtech.device.DeviceInterface'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
DEVICE_PUB_IFACE = 'com.lairdtech.device.public.DeviceInterface'

"""
Status codes from the Storage Service
"""
EXT_STORAGE_STATUS_FULL = -1
EXT_STORAGE_STATUS_FAILED = -2
EXT_STORAGE_STATUS_STOP_FAILED = -3
EXT_STORAGE_STATUS_READY = 0
EXT_STORAGE_STATUS_NOTPRESENT = 1
EXT_STORAGE_STATUS_UNFORMATTED = 2
EXT_STORAGE_STATUS_FORMATTING = 3
EXT_STORAGE_STATUS_STOPPING = 4
EXT_STORAGE_STATUS_STOPPED = 5

"""
Swap Status codes
"""
STORAGE_EJECTING = 'ejecting'
STORAGE_STOPPED = 'stopped'
STORAGE_INSERTING = 'inserting'
STORAGE_FORMATTING = 'formatting'

"""
Misc
"""
EXT_STORAGE_STATUS_PROP = 'ExtStorageStatus'
STORAGE_SWAP_TIMER_MS = 2000

class DeviceManager():
    """Device States - these must match the IG Device Service
    """
    
    def __init__(self, response_cb):
        try:
            # Connect to the Device Service through DBUS. If unable, disable the 
            # Device API to message manager
            self.bus = dbus.SystemBus()
            self.device_props = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
            DEVICE_SVC_PATH), DBUS_PROP_IFACE)
            self.device_props.connect_to_signal('PropertiesChanged', self.dev_props_changed)
            self.device_svc = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
                DEVICE_SVC_PATH), DEVICE_PUB_IFACE)

            self.id_swap_timer = None
            self.swap_status = None
            self.ext_storage_status = self.device_props.Get(DEVICE_PUB_IFACE, EXT_STORAGE_STATUS_PROP)
            self.response_cb = response_cb
            self.api_enabled = True
        except dbus.DBusException:
            self.api_enabled = False

    def storage_swap_cb(self):
        """Callback for intermediate status of the storage swap.  This will create
        a response from Message Manager with an intermediate swap status.
        """
        # Send intermediate response with current swap state
        syslog('Sending intermediate swap status: {}'.format(self.swap_status))
        self.response_cb(MSG_STATUS_INTERMEDIATE, {'state' : self.swap_status})
        return True # Continue timer

    def do_storage_swap(self):
        """Kick off a storage swap. Returns a MSG Status to include in the response. 
        """
        # Check that we're not already performing a swap
        if self.id_swap_timer:
            return MSG_STATUS_ERR_INVALID

        # Check current external storage state
        if (self.ext_storage_status == EXT_STORAGE_STATUS_FULL or
            self.ext_storage_status == EXT_STORAGE_STATUS_FAILED or
            self.ext_storage_status == EXT_STORAGE_STATUS_STOP_FAILED or
            self.ext_storage_status == EXT_STORAGE_STATUS_READY):
            # Card is present, request stop
            syslog('Ejecting external storage')
            self.swap_status = STORAGE_EJECTING
            if self.device_svc.ExtStorageStop() != 0:
                syslog('Failed request to stop external storage.')
                return MSG_STATUS_ERR_DEVICE
        elif self.ext_storage_status == EXT_STORAGE_STATUS_STOPPING:
            # Already stopping
            self.swap_status = STORAGE_EJECTING
        elif self.ext_storage_status == EXT_STORAGE_STATUS_UNFORMATTED:
            # Unformatted card is present, start formatting
            syslog('Formatting external storage')
            self.swap_status = STORAGE_FORMATTING
            if self.device_svc.ExtStorageFormat() != 0:
                syslog('Failed request to format external storage.')
                return MSG_STATUS_ERR_DEVICE
        elif self.ext_storage_status == EXT_STORAGE_STATUS_FORMATTING:
            # Already formatting
            self.swap_status = STORAGE_FORMATTING
        elif self.ext_storage_status == EXT_STORAGE_STATUS_STOPPED:
            # Already stopped
            self.swap_status = STORAGE_STOPPED
        elif self.ext_storage_status == EXT_STORAGE_STATUS_NOTPRESENT:
            # Card already removed
            self.swap_status = STORAGE_INSERTING
        else:
            # Unknown state?
            syslog('Unknown storage state: {}'.format(self.ext_storage_status))
            return MSG_STATUS_ERR_INVALID

        # Set timer task to check status & send intermediate responses
        self.id_swap_timer = gobject.timeout_add(STORAGE_SWAP_TIMER_MS, self.storage_swap_cb)
        # Send initial intermediate response
        return (MSG_STATUS_INTERMEDIATE, {'state' : self.swap_status})

    def get_storage_data(self):
        """Get the storage info properties from the Device Service
        """
        props = self.device_props.GetAll(DEVICE_PUB_IFACE)
        storage_data = { 'intBytesTotal' : props['IntStorageTotalBytes'],
            'intBytesFree' : props['IntStorageFreeBytes'],
            'extBytesTotal' : props['ExtStorageTotalBytes'],
            'extBytesFree' : props['ExtStorageFreeBytes'],
            'canSwap' : props['ExtStorageStatus'] != EXT_STORAGE_STATUS_NOTPRESENT }
        return storage_data

    def dev_props_changed(self, iface, props_changed, props_invalidated):
        """Handles the properties changed event of the Device Service 
        properties. This will create a response from Message Manager 
        with a swap status. 
        """
        if not props_changed or EXT_STORAGE_STATUS_PROP not in props_changed:
            return 

        if not self.id_swap_timer:
            return 

        self.ext_storage_status = props_changed[EXT_STORAGE_STATUS_PROP]
        syslog('External storage state changed: {}'.format(self.ext_storage_status))
        # Handle change in state while swap is in progress
        # Stop current timer
        gobject.source_remove(self.id_swap_timer)
        self.id_swap_timer = None
        if self.ext_storage_status == EXT_STORAGE_STATUS_STOPPED:
            self.swap_status = STORAGE_STOPPED
        elif self.ext_storage_status == EXT_STORAGE_STATUS_READY:
            # Card is now in use, send final result
            self.response_cb(MSG_STATUS_SUCCESS)
            return
        elif self.ext_storage_status == EXT_STORAGE_STATUS_NOTPRESENT:
            # Card removed, make sure we were expecting this
            if self.swap_status != STORAGE_STOPPED:
                self.response_cb(MSG_STATUS_ERR_INVALID)
                return
            self.swap_status = STORAGE_INSERTING
        elif self.ext_storage_status == EXT_STORAGE_STATUS_UNFORMATTED:
            # Unformatted card inserted
            syslog('Formatting external storage')
            self.swap_status = STORAGE_FORMATTING
            if self.device_svc.ExtStorageFormat() != 0:
                syslog('Failed request to format external storage.')
                self.response_cb(MSG_STATUS_ERR_DEVICE)
                return
        elif self.ext_storage_status == EXT_STORAGE_STATUS_STOPPING:
            self.swap_status = STORAGE_EJECTING
        elif self.ext_storage_status == EXT_STORAGE_STATUS_FORMATTING:
            self.swap_status = STORAGE_FORMATTING
        else:
            # All other states are failures
            self.response_cb(MSG_STATUS_ERR_DEVICE)
            return

        # Set timer task to check status & send intermediate responses
        self.id_swap_timer = gobject.timeout_add(STORAGE_SWAP_TIMER_MS,
            self.storage_swap_cb)

    def get_device_type(self):
        if self.api_enabled == True:
            return self.device_svc.Identify()
        else:
            syslog('self.device_svc is none')
            return '0'

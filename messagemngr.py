import dbus, dbus.service, dbus.exceptions
import json
import time
from netmngr import NetManager
from provmngr import ProvManager
from syslog import syslog

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
else:
    import gobject

''' JSON Message Strings '''
MSG_VERSION = 'version'
MSG_ID = 'id'
MSG_TYPE = 'type'
MSG_STATUS = 'status'
MSG_DATA = 'data'

MSG_VERSION_VAL = 1

MSG_ID_VERSION = 'version'
MSG_ID_GET_DEVICE_ID = 'getDeviceId'
MSG_ID_GET_APS = 'getAccessPoints'
MSG_ID_CONNECT_AP = 'connectAP'
MSG_ID_PROVISION_URL = 'provisionURL'
MSG_ID_GET_DEVICE_CAPS = 'getDeviceCaps'
MSG_ID_GET_STORAGE_INFO = 'getStorageInfo'
MSG_ID_EXT_STORAGE_SWAP = 'extStorageSwap'

MSG_STATUS_INTERMEDIATE = 1
MSG_STATUS_SUCCESS = 0
MSG_STATUS_ERR_INVALID = -1
MSG_STATUS_ERR_TIMEOUT = -2
MSG_STATUS_ERR_AUTH = -3
MSG_STATUS_ERR_NOTFOUND = -4
MSG_STATUS_ERR_NOCONN = -5
MSG_STATUS_ERR_DEVICE = -6

EXT_STORAGE_STATUS_FULL = -1
EXT_STORAGE_STATUS_FAILED = -2
EXT_STORAGE_STATUS_STOP_FAILED = -3
EXT_STORAGE_STATUS_READY = 0
EXT_STORAGE_STATUS_NOTPRESENT = 1
EXT_STORAGE_STATUS_UNFORMATTED = 2
EXT_STORAGE_STATUS_FORMATTING = 3
EXT_STORAGE_STATUS_STOPPING = 4
EXT_STORAGE_STATUS_STOPPED = 5

STORAGE_EJECTING = 'ejecting'
STORAGE_STOPPED = 'stopped'
STORAGE_INSERTING = 'inserting'
STORAGE_FORMATTING = 'formatting'

GET_AP_INTERMEDIATE_TIMEOUT = 2
ACTIVATION_INTERMEDIATE_TIMEOUT = 5
ACTIVATION_FAILURE_TIMEOUT = 60
ACTIVATION_TIMER_MS = 500

PROVISION_INTERMEDIATE_TIMEOUT = 2
PROVISION_TIMER_MS = 500

DEVICE_SVC_NAME = 'com.lairdtech.device.DeviceService'
DEVICE_SVC_PATH = '/com/lairdtech/device/DeviceService'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'
DEVICE_PUB_IFACE = 'com.lairdtech.device.public.DeviceInterface'
EXT_STORAGE_STATUS_PROP = 'ExtStorageStatus'

STORAGE_SWAP_TIMER_MS = 2000

def convert_dict_keys_values_to_string(data):
    """Convert dict's keys & values from 'bytes' to 'string'
    """
    if isinstance(data, bytes):
        return data.decode("utf-8")
    if isinstance(data, dict):
        return dict(map(convert_dict_keys_values_to_string, data.items()))
    if isinstance(data, tuple):
        return tuple(map(convert_dict_keys_values_to_string, data))
    if isinstance(data, list):
        return list(map(convert_dict_keys_values_to_string, data))
    if isinstance(data, set):
        return set(map(convert_dict_keys_values_to_string, data))
    return data


class MessageManager():
    def __init__(self, net_manager, shutdown_cb):
        self.net_manager = net_manager
        self.prov_manager = ProvManager()
        self.shutdown_cb = shutdown_cb
        self.activation_start_time = 0
        self.activation_msg_time = 0
        self.provision_msg_time = 0
        self.ap_first_scan = False
        self.cur_req_obj = None
        self.ap_scanning = False
        self.id_swap_timer = None
        self.swap_status = None
        self.bus = dbus.SystemBus()
        self.device_props = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
            DEVICE_SVC_PATH), DBUS_PROP_IFACE)
        self.device_props.connect_to_signal('PropertiesChanged', self.dev_props_changed)
        self.device_svc = dbus.Interface(self.bus.get_object(DEVICE_SVC_NAME,
            DEVICE_SVC_PATH), DEVICE_PUB_IFACE)
        self.ext_storage_status = self.device_props.Get(DEVICE_PUB_IFACE, EXT_STORAGE_STATUS_PROP)

    def is_provisioned(self):
        return self.prov_manager.get_prov_state() == ProvManager.PROV_COMPLETE_SUCCESS

    def start(self, tx_msg):
        self.tx_msg = tx_msg

    def add_request(self, req_obj):
        """Schedule request handler to run on main loop
        """
        # Cancel any current AP scan
        self.ap_scanning = False
        gobject.timeout_add(0, self.handle_command, req_obj)

    def client_disconnect(self):
        # Reset message state on client disconnect
        syslog('BLE client disconnected, resetting state.')
        self.ap_scanning = False

    def send_response(self, req_obj, status, data=None, tx_complete=None):
        """Send a response message based on the request, with optional data
        """
        try:
            resp_obj = { MSG_VERSION : MSG_VERSION_VAL, MSG_ID : req_obj[MSG_ID],
                     MSG_TYPE : req_obj[MSG_TYPE], MSG_STATUS : status }
            if data:
                resp_obj[MSG_DATA] = data
            syslog('Sending {} response ({})'.format(resp_obj[MSG_TYPE], resp_obj[MSG_STATUS]))
            self.tx_msg(json.dumps(resp_obj, separators=(',',':')), tx_complete)
        except Exception as e:
            syslog("Failed to send response: '%s'" % str(e))

    def handle_command(self, req_obj):
        """Process a request object
        """
        try:
            msg_type = req_obj[MSG_TYPE]
            syslog('Processing request: {}'.format(msg_type))
            # Check version on all messages except the version check!
            if msg_type != MSG_ID_VERSION and req_obj[MSG_VERSION] != MSG_VERSION_VAL:
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
                return
            if msg_type == MSG_ID_VERSION:
                self.send_response(req_obj, MSG_STATUS_SUCCESS)
            elif msg_type == MSG_ID_GET_DEVICE_ID:
                self.req_get_device_id(req_obj)
            elif msg_type == MSG_ID_GET_APS:
                self.req_get_access_points(req_obj)
            elif msg_type == MSG_ID_CONNECT_AP:
                self.req_connect_ap(req_obj)
            elif msg_type == MSG_ID_PROVISION_URL:
                self.req_provision_url(req_obj)
            elif msg_type == MSG_ID_GET_DEVICE_CAPS:
                self.req_get_device_caps(req_obj)
            elif msg_type == MSG_ID_GET_STORAGE_INFO:
                self.req_get_storage_info(req_obj)
            elif msg_type == MSG_ID_EXT_STORAGE_SWAP:
                self.req_ext_storage_swap(req_obj)
            else:
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
        except KeyError:
            syslog('Invalid request message, ignoring.')
        # Exit timer
        return False

    def req_get_device_id(self, req_obj):
        """Handle Get Device ID request
        """
        # Read version as last string in release file line
        with open('/etc/laird-release', 'r') as f:
            ver_raw = f.read()
        version = ver_raw.rstrip().split(' ')[-1]
        id_data = { 'deviceId' : self.net_manager.get_wlan_hw_address(),
            'name' : 'Laird Sentrius IG60', 'version' : version}
        self.send_response(req_obj, MSG_STATUS_SUCCESS, data=id_data)

    def req_get_device_caps(self, req_obj):
        """Handle Get Device Capabilities Request
        """
        cap_data = { 'isProvisioned' : self.is_provisioned(),
            'deviceCaps' : ['getStorageInfo', 'extStorageSwap'] }
        self.send_response(req_obj, MSG_STATUS_SUCCESS, data=cap_data)

    """
    NOTE: For some reason, using the NetworkManager API to query each
          AP object is very slow, so we process the AP list
          in batches and send them to the client.  Also, reading the APs
          causes the Tx on the BLE GATT characteristic to slow down,
          which leads to long delays (timeouts) for the client.  So,
          the code below implements a callback when the BLE Tx is
          complete.  Thus we only process the AP list after the last
          message was sent, then send the message once we've processed
          the AP list; this ends up being more responsive to the client.
    """
    def ap_scan_tx_complete(self):
        """Callback for AP scan list TX complete
        """
        # Only continue if scanning was not cancelled
        if self.ap_scanning:
            # Schedule call on main loop to process more results
            gobject.timeout_add(0, self.get_ap_cb)

    def get_ap_cb(self):
        """Timer callback to process AP list
        """
        aplist = self.net_manager.get_access_points(GET_AP_INTERMEDIATE_TIMEOUT, not self.ap_first_scan)
        self.ap_first_scan = False
        # Only continue if scanning was not cancelled
        if self.ap_scanning:
            if aplist and len(aplist) > 0:
                # Send response with TX complete callback to get more
                syslog('Sending intermediate list of {} APs.'.format(len(aplist)))
                self.send_response(self.cur_req_obj, MSG_STATUS_INTERMEDIATE, data=aplist, tx_complete=self.ap_scan_tx_complete)
            else:
                # Send final response
                syslog('Sending final AP response')
                self.send_response(self.cur_req_obj, MSG_STATUS_SUCCESS)
                self.cur_req_obj = None
                self.ap_scanning = False

    def req_get_access_points(self, req_obj):
        """Handle Get Access Points request
        """
        self.cur_req_obj = req_obj
        self.ap_first_scan = True
        self.ap_scanning = True
        # Send response indicating request in progress, with TX complete callback to scan
        self.send_response(req_obj, MSG_STATUS_INTERMEDIATE, tx_complete=self.ap_scan_tx_complete)

    def check_activation(self, req_obj):
        status = self.net_manager.get_activation_status()
        if status == NetManager.ACTIVATION_SUCCESS:
            self.send_response(req_obj, MSG_STATUS_SUCCESS)
            return False # Exit timer
        elif status == NetManager.ACTIVATION_FAILED_AUTH:
            self.send_response(req_obj, MSG_STATUS_ERR_AUTH)
            self.net_manager.activation_cleanup()
            return False # Exit timer
        elif status == NetManager.ACTIVATION_FAILED_NETWORK:
            self.send_response(req_obj, MSG_STATUS_ERR_NOCONN)
            self.net_manager.activation_cleanup()
            return False # Exit timer
        if time.time() - self.activation_start_time > ACTIVATION_FAILURE_TIMEOUT:
            # Failed to activate before timeout, send failure and exit timer
            self.send_response(req_obj, MSG_STATUS_ERR_NOCONN)
            self.net_manager.activation_cleanup()
            return False
        elif time.time() - self.activation_msg_time > ACTIVATION_INTERMEDIATE_TIMEOUT:
            # Still waiting for activation, send intermediate response
            self.send_response(req_obj, MSG_STATUS_INTERMEDIATE)
            self.activation_msg_time = time.time()
        return True

    def req_connect_ap(self, req_obj):
        """Handle Connect to AP message
        """
        try:
            if self.is_provisioned():
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
                return
            # Cancel AP scan if in progress
            self.ap_scanning = False
            # Issue request to Network Manager
            if 'data' in req_obj and self.net_manager.activate_connection(convert_dict_keys_values_to_string(req_obj['data'])):
                # Config succeeded, connection in progress
                self.send_response(req_obj, MSG_STATUS_INTERMEDIATE)
                # Set timer task to check connectivity
                self.activation_start_time = time.time()
                self.activation_msg_time = self.activation_start_time
                gobject.timeout_add(ACTIVATION_TIMER_MS, self.check_activation, req_obj)
            else:
                # Failed to create connection from configuration
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
        except Exception as e:
            syslog("Failed to connect ap: '%s'" % str(e))

    def send_prov_response(self, req_obj, status):
        if status == ProvManager.PROV_COMPLETE_SUCCESS:
            self.send_response(req_obj, MSG_STATUS_SUCCESS)
            # Shutdown provisioning service
            self.shutdown_cb()
            return False
        elif status == ProvManager.PROV_FAILED_AUTH:
            self.send_response(req_obj, MSG_STATUS_ERR_AUTH)
            return False
        elif status == ProvManager.PROV_FAILED_TIMEOUT:
            self.send_response(req_obj, MSG_STATUS_ERR_TIMEOUT)
            return False
        elif status == ProvManager.PROV_FAILED_CONNECT:
            self.send_response(req_obj, MSG_STATUS_ERR_NOTFOUND)
            return False
        elif status < 0: # All other failures
            self.send_response(req_obj, MSG_STATUS_ERR_NOCONN)
            return False
        else:
            # Intermediate status, don't send
            return True

    def check_provision(self, req_obj):
        # Cancel AP scan if in progress
        self.ap_scanning = False
        status = self.prov_manager.get_prov_state()
        ret = self.send_prov_response(req_obj, status)
        if ret and time.time() - self.provision_msg_time > PROVISION_INTERMEDIATE_TIMEOUT:
            # Still waiting for completion, send intermediate response
            self.provision_msg_time = time.time()
            if status == ProvManager.PROV_INPROGRESS_DOWNLOADING:
                data = {'operation' : 'download'}
            elif status == ProvManager.PROV_INPROGRESS_APPLYING:
                data = {'operation' : 'apply'}
            else:
                data = None
            self.send_response(req_obj, MSG_STATUS_INTERMEDIATE, data)
        return ret

    def req_provision_url(self, req_obj):
        """Handle Provision message
        """
        if self.is_provisioned():
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
            return
        # Issue request to Provisoning Manager
        if 'data' in req_obj:
            status = self.prov_manager.start_provisioning(convert_dict_keys_values_to_string(req_obj['data']))
            if self.send_prov_response(req_obj, status):
                # Success, send actualt response
                self.send_response(req_obj, MSG_STATUS_INTERMEDIATE,
                    {'operation' : 'connect'})
                # Set timer task to check status & sent intermediate responses
                self.provision_msg_time = time.time()
                gobject.timeout_add(PROVISION_TIMER_MS, self.check_provision, req_obj)
            else:
                # Failed, response already sent
                pass
        else:
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)

    def req_get_storage_info(self, req_obj):
        """Handle Get Storage Info request
        """
        props = self.device_props.GetAll(DEVICE_PUB_IFACE)
        storage_data = { 'intBytesTotal' : props['IntStorageTotalBytes'],
            'intBytesFree' : props['IntStorageFreeBytes'],
            'extBytesTotal' : props['ExtStorageTotalBytes'],
            'extBytesFree' : props['ExtStorageFreeBytes'],
            'canSwap' : props['ExtStorageStatus'] != EXT_STORAGE_STATUS_NOTPRESENT }
        self.send_response(req_obj, MSG_STATUS_SUCCESS, data=storage_data)

    def dev_props_changed(self, iface, props_changed, props_invalidated):
        if props_changed and EXT_STORAGE_STATUS_PROP in props_changed:
            self.ext_storage_status = props_changed[EXT_STORAGE_STATUS_PROP]
            syslog('External storage state changed: {}'.format(self.ext_storage_status))
            # Handle change in state while swap is in progress
            if self.id_swap_timer:
                # Stop current timer
                gobject.source_remove(self.id_swap_timer)
                self.id_swap_timer = None
                if self.ext_storage_status == EXT_STORAGE_STATUS_STOPPED:
                    self.swap_status = STORAGE_STOPPED
                elif self.ext_storage_status == EXT_STORAGE_STATUS_READY:
                    # Card is now in use, send final result
                    self.send_response(self.cur_req_obj, MSG_STATUS_SUCCESS)
                    self.cur_req_obj = None
                    return
                elif self.ext_storage_status == EXT_STORAGE_STATUS_NOTPRESENT:
                    # Card removed, make sure we were expecting this
                    if self.swap_status != STORAGE_STOPPED:
                        self.send_response(self.cur_req_obj, MSG_STATUS_ERR_INVALID)
                        self.cur_req_obj = None
                        return
                    self.swap_status = STORAGE_INSERTING
                elif self.ext_storage_status == EXT_STORAGE_STATUS_UNFORMATTED:
                    # Unformatted card inserted
                    syslog('Formatting external storage')
                    self.swap_status = STORAGE_FORMATTING
                    if self.device_svc.ExtStorageFormat() != 0:
                        syslog('Failed request to format external storage.')
                        self.send_response(self.cur_req_obj, MSG_STATUS_ERR_DEVICE)
                        self.cur_req_obj = None
                        return
                elif self.ext_storage_status == EXT_STORAGE_STATUS_STOPPING:
                    self.swap_status = STORAGE_EJECTING
                elif self.ext_storage_status == EXT_STORAGE_STATUS_FORMATTING:
                    self.swap_status = STORAGE_FORMATTING
                else:
                    # All other states are failures
                    self.send_response(self.cur_req_obj, MSG_STATUS_ERR_DEVICE)
                    self.cur_req_obj = None
                    return
                # Set timer task to check status & send intermediate responses
                self.id_swap_timer = gobject.timeout_add(STORAGE_SWAP_TIMER_MS,
                    self.storage_swap_cb)

    def storage_swap_cb(self):
        # Send intermediate response with current swap state
        syslog('Sending intermediate swap status: {}'.format(self.swap_status))
        self.send_response(self.cur_req_obj, MSG_STATUS_INTERMEDIATE, {'state' : self.swap_status})
        return True # Continue timer

    def req_ext_storage_swap(self, req_obj):
        """Handle Storage Swap request
        """
        # Check that we're not already performing a swap
        if self.id_swap_timer:
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
            return
        self.cur_req_obj = req_obj
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
                self.send_response(req_obj, MSG_STATUS_ERR_DEVICE)
                return
        elif self.ext_storage_status == EXT_STORAGE_STATUS_STOPPING:
            # Already stopping
            self.swap_status = STORAGE_EJECTING
        elif self.ext_storage_status == EXT_STORAGE_STATUS_UNFORMATTED:
            # Unformatted card is present, start formatting
            syslog('Formatting external storage')
            self.swap_status = STORAGE_FORMATTING
            if self.device_svc.ExtStorageFormat() != 0:
                syslog('Failed request to format external storage.')
                self.send_response(req_obj, MSG_STATUS_ERR_DEVICE)
                return
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
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
            return
        # Set timer task to check status & send intermediate responses
        self.id_swap_timer = gobject.timeout_add(STORAGE_SWAP_TIMER_MS, self.storage_swap_cb)
        # Send initial intermediate response
        self.send_response(req_obj, MSG_STATUS_INTERMEDIATE, {'state' : self.swap_status})

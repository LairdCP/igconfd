import dbus, dbus.service, dbus.exceptions
import json
import time

from netmngr import NetManager
from provmngr import ProvManager
from devmngr import DeviceManager

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

MSG_VERSION_VAL = 2

MSG_ID_VERSION = 'version'
MSG_ID_GET_DEVICE_ID = 'getDeviceId'
MSG_ID_GET_APS = 'getAccessPoints'
MSG_ID_CONNECT_AP = 'connectAP'
MSG_ID_UPDATE_APS = 'updateAPS'
MSG_ID_GET_CURRENT_APS = 'getAPS'
MSG_ID_CONNECT_LTE = 'connectLTE'
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
MSG_STATUS_API_DISABLED = -7
MSG_STATUS_ERR_NOSIM = -8
MSG_STATUS_ERR_BAD_CONFIG = -9
MSG_STATUS_ERR_UNKNOWN = -10

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
    def __init__(self, shutdown_cb):
        self.prov_manager = ProvManager(self.send_prov_response)
        self.dev_manager = DeviceManager(self.send_response)
        self.net_manager = NetManager(self.send_net_response)

        self.shutdown_cb = shutdown_cb
        self.cur_req_obj = None
        self.msg_timeout_id = None
        self.msg_timeout_cb = None
        self.msg_timeout_delay = None

    def start(self, tx_msg):
        self.tx_msg = tx_msg

    def add_request(self, req_obj):
        """Schedule request handler to run on main loop
        """
        # Cancel any current AP scan
        self.net_manager.stop_scanning()
        gobject.timeout_add(0, self.handle_command, req_obj)

    def client_disconnect(self):
        # Reset message state on client disconnect
        syslog('BLE client disconnected, resetting state.')
        self.net_manager.stop_scanning()

    def reset_msg_timeout(self):
        if self.msg_timeout_id is not None:
            gobject.source_remove(self.msg_timeout_id)
            self.msg_timeout_id = None
        if self.msg_timeout_cb is not None and self.msg_timeout_delay is not None:
            self.msg_timeout_id = gobject.timeout_add(self.msg_timeout_delay, self.msg_timeout_cb)

    def set_msg_timeout(self, msg_timeout_delay, msg_timeout_cb):
        self.msg_timeout_delay = msg_timeout_delay
        self.msg_timeout_cb = msg_timeout_cb
        self.reset_msg_timeout()

    def send_response(self, req_obj, status, data=None, tx_complete=None):
        """Send a response message based on the request, with optional data
        """
        self.reset_msg_timeout()
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
        self.reset_msg_timeout()
        try:
            msg_type = req_obj[MSG_TYPE]
            syslog('Processing request: {}'.format(msg_type))
            # Check version on all messages except the version check;
            # don't allow future versions (client must be backwards
            # compatible)
            if msg_type != MSG_ID_VERSION and req_obj[MSG_VERSION] > MSG_VERSION_VAL:
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
                return
            if msg_type == MSG_ID_VERSION:
                self.send_response(req_obj, MSG_STATUS_SUCCESS)
            elif msg_type == MSG_ID_GET_DEVICE_ID:
                self.req_get_device_id(req_obj)
            elif msg_type == MSG_ID_GET_DEVICE_CAPS:
                self.req_get_device_caps(req_obj)
            elif msg_type == MSG_ID_GET_APS:
                self.handle_net_manager_request(MSG_ID_GET_APS, req_obj)
            elif msg_type == MSG_ID_CONNECT_AP:
                self.handle_net_manager_request(MSG_ID_CONNECT_AP, req_obj)
            elif msg_type == MSG_ID_UPDATE_APS:
                self.handle_net_manager_request(MSG_ID_UPDATE_APS, req_obj)
            elif msg_type == MSG_ID_GET_CURRENT_APS:
                self.handle_net_manager_request(MSG_ID_GET_CURRENT_APS, req_obj)
            elif msg_type == MSG_ID_CONNECT_LTE:
                self.handle_net_manager_request(MSG_ID_CONNECT_LTE, req_obj)
            elif msg_type == MSG_ID_PROVISION_URL:
                self.handle_prov_manager_request(MSG_ID_PROVISION_URL, req_obj)
            elif msg_type == MSG_ID_GET_STORAGE_INFO:
                self.handle_dev_manager_request(MSG_ID_GET_STORAGE_INFO, req_obj)
            elif msg_type == MSG_ID_EXT_STORAGE_SWAP:
                self.handle_dev_manager_request(MSG_ID_EXT_STORAGE_SWAP, req_obj)
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
        cap_data = {}

        cap_data['isProvisioned'] = self.prov_manager.is_provisioned()

        if self.prov_manager.api_enabled:
            cap_data.setdefault('deviceCaps', []).append('provisionURL')
            cap_data.setdefault('deviceCaps', []).extend(['getStorageInfo', 'extStorageSwap'])

        if self.net_manager.is_modem_available():
            cap_data.setdefault('deviceCaps', []).append('connectLTE')

        self.send_response(req_obj, MSG_STATUS_SUCCESS, data=cap_data)

    """
    Response callbacks for the various service managers
    """
    def send_net_response(self, status, data=None, tx_complete=None):
        if status == NetManager.ACTIVATION_SUCCESS or status == NetManager.AP_SCANNING_SUCCESS:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_SUCCESS, data)
        elif status == NetManager.ACTIVATION_FAILED_AUTH:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_ERR_AUTH)
        elif status == NetManager.ACTIVATION_FAILED_NETWORK:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_ERR_NOCONN)
        elif status == NetManager.ACTIVATION_NO_SIM:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_ERR_NOSIM)
        elif status == NetManager.ACTIVATION_NO_CONN:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_ERR_NOCONN)
            self.net_manager.activation_cleanup()
        elif status == NetManager.ACTIVATION_PENDING or status == NetManager.AP_SCANNING:
            self.send_response(self.cur_net_req_obj, MSG_STATUS_INTERMEDIATE, data, tx_complete)

    def lte_autoconnect_status(self, status, data=None, tx_complete=None):
        if status == NetManager.ACTIVATION_PENDING or status == NetManager.AP_SCANNING:
            # LTE connect is still pending, send intermediate status
            resp_data = {'operation' : 'LTE autoconnect'}
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_INTERMEDIATE, resp_data, tx_complete)
        else:
            # LTE connect has completed (success or failure); continue provisioning
            self.prov_manager.start_provisioning(convert_dict_keys_values_to_string(self.cur_prov_req_obj['data']))

    def send_prov_response(self, status, data=None):
        if status == ProvManager.PROV_COMPLETE_SUCCESS:
            # Shutdown provisioning service and disabled the api
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_SUCCESS)
            self.prov_manager.disable_api()
            self.shutdown_cb()
        elif status == ProvManager.PROV_FAILED_AUTH:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_AUTH)
        elif status == ProvManager.PROV_FAILED_TIMEOUT:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_TIMEOUT)
        elif status == ProvManager.PROV_FAILED_CONNECT:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_NOCONN)
        elif status == ProvManager.PROV_FAILED_NOT_FOUND:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_NOTFOUND)
        elif status == ProvManager.PROV_FAILED_BAD_CONFIG:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_BAD_CONFIG)
        elif status == ProvManager.PROV_FAILED_INVALID:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_INVALID)
        elif status < 0: # All other failures
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_ERR_UNKNOWN)
        else:
            self.send_response(self.cur_prov_req_obj, MSG_STATUS_INTERMEDIATE, data)

    def send_dev_reponse(self, status, data=None):
        self.send_response(self.cur_req_obj, status, data)
        self.cur_req_obj = None

    """
    Request handlers for the various service managers
    """
    def handle_net_manager_request(self, msg_type, req_obj):
        self.cur_net_req_obj = req_obj

        if self.prov_manager.api_enabled and self.prov_manager.is_provisioned():
            self.send_prov_response(self.cur_net_req_obj, MSG_STATUS_ERR_INVALID)
            return

        if msg_type == MSG_ID_GET_APS:
             self.net_manager.req_get_access_points()
        elif msg_type == MSG_ID_CONNECT_AP and 'data' in req_obj:
             self.net_manager.req_connect_ap(convert_dict_keys_values_to_string(self.cur_net_req_obj['data']))
        elif msg_type == MSG_ID_CONNECT_LTE:
             if 'data' in req_obj:
                 params = convert_dict_keys_values_to_string(self.cur_net_req_obj['data'])
             else:
                 params = {}
             self.net_manager.req_connect_lte(params)
        elif msg_type == MSG_ID_UPDATE_APS and 'data' in self.cur_net_req_obj:
            ret = self.net_manager.req_update_aps(convert_dict_keys_values_to_string(self.cur_net_req_obj['data']))
            if ret:
                self.send_net_response(NetManager.ACTIVATION_SUCCESS)
            else:
                self.send_net_response(NetManager.ACTIVATION_FAILED_NETWORK)
        elif msg_type == MSG_ID_GET_CURRENT_APS:
            aps = self.net_manager.req_get_aps()
            if aps is not None:
                self.send_net_response(NetManager.ACTIVATION_SUCCESS, data=aps)
            else:
                self.send_net_response(NetManager.ACTIVATION_FAILED_NETWORK)

    def handle_prov_manager_request(self, msg_type, req_obj):

        if self.net_manager.api_enabled:
            self.net_manager.stop_scanning()

        self.cur_prov_req_obj = req_obj
        if self.prov_manager.api_enabled:
            if msg_type == MSG_ID_PROVISION_URL and 'data' in req_obj:
                # If the LTE modem is available and has not been
                # configured, AND this request has the legacy version (1),
                # configure the default LTE profile before performing
                # provisioning via URL; this enables use of the
                # LTE modem when using the legacy mobile application.
                if req_obj['version'] == 1 and self.net_manager.is_modem_available() and not self.net_manager.is_lte_configured():
                    self.net_manager.req_connect_lte({}, self.lte_autoconnect_status)
                else:
                    self.prov_manager.start_provisioning(convert_dict_keys_values_to_string(req_obj['data']))
        else:
            self.send_prov_response(MSG_STATUS_ERR_INVALID, self.cur_prov_req_obj)

    def handle_dev_manager_request(self, msg_type, req_obj):
        if self.dev_manager.api_enabled:
            self.cur_dev_req_obj = req_obj

            if msg_type == MSG_ID_GET_STORAGE_INFO:
                storage_data = self.dev_manager.get_storage_data()
                self.send_response(self.cur_dev_req_obj, MSG_STATUS_SUCCESS, data=storage_data)
            elif msg_type == MSG_ID_EXT_STORAGE_SWAP:
                status, storage_data = self.dev_manager.do_storage_swap()
                self.send_response(self.cur_dev_req_obj, status, data=storage_data)
        else:
            self.send_response(self.cur_dev_req_obj, MSG_STATUS_ERR_INVALID)



 
 

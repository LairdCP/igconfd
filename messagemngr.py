import json
import time
from netmngr import NetManager
from provmngr import ProvManager
from syslog import syslog

try:
  from gi.repository import GObject
except ImportError:
  import gobject as GObject

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

MSG_STATUS_INTERMEDIATE = 1
MSG_STATUS_SUCCESS = 0
MSG_STATUS_ERR_INVALID = -1
MSG_STATUS_ERR_TIMEOUT = -2
MSG_STATUS_ERR_AUTH = -3
MSG_STATUS_ERR_NOTFOUND = -4
MSG_STATUS_ERR_NOCONN = -5

GET_AP_INTERMEDIATE_TIMEOUT = 2
ACTIVATION_INTERMEDIATE_TIMEOUT = 5
ACTIVATION_FAILURE_TIMEOUT = 15
ACTIVATION_TIMER_MS = 500

PROVISION_INTERMEDIATE_TIMEOUT = 2
PROVISION_TIMER_MS = 500

class MessageManager():
    def __init__(self, shutdown_cb):
        self.net_manager = NetManager()
        self.prov_manager = ProvManager()
        self.shutdown_cb = shutdown_cb
        self.activation_start_time = 0
        self.activation_msg_time = 0
        self.provision_msg_time = 0

    def is_provisioned(self):
        return self.prov_manager.get_prov_state() == ProvManager.PROV_COMPLETE_SUCCESS

    def start(self, tx_msg):
        self.tx_msg = tx_msg

    def add_request(self, req_obj):
        """Schedule request handler to run on main loop
        """
        GObject.timeout_add(0, self.handle_command, req_obj)

    def send_response(self, req_obj, status, data=None):
        """Send a response message based on the request, with optional data
        """
        resp_obj = { MSG_VERSION : MSG_VERSION_VAL, MSG_ID : req_obj[MSG_ID],
                     MSG_TYPE : req_obj[MSG_TYPE], MSG_STATUS : status }
        if data:
            resp_obj[MSG_DATA] = data
        self.tx_msg(json.dumps(resp_obj, separators=(',',':')))

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
            else:
                self.send_response(req_obj, MSG_STATUS_ERR_INVALID)
        except KeyError:
            syslog('Invalid request message, ignoring.')
        # Exit timer
        return False

    def req_get_device_id(self, req_obj):
        """Handle Get Device ID request
        """
        dev_id = { 'deviceId' : self.net_manager.get_wlan_hw_address() }
        self.send_response(req_obj, MSG_STATUS_SUCCESS, data=dev_id)

    def req_get_access_points(self, req_obj):
        """Handle Get Access Points request
        """
        # Send response indicating request in progress
        self.send_response(req_obj, MSG_STATUS_INTERMEDIATE)
        # Collect APs with a timeout & send
        aplist = self.net_manager.get_access_points(GET_AP_INTERMEDIATE_TIMEOUT)
        while aplist and len(aplist) > 0:
            self.send_response(req_obj, MSG_STATUS_INTERMEDIATE, data=aplist)
            aplist = self.net_manager.get_access_points(GET_AP_INTERMEDIATE_TIMEOUT, True)
        # Send final response
        self.send_response(req_obj, MSG_STATUS_SUCCESS)

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
        # Issue request to Network Manager
        if 'data' in req_obj and self.net_manager.activate_connection(req_obj['data']):
            # Config succeeded, connection in progress
            self.send_response(req_obj, MSG_STATUS_INTERMEDIATE)
            # Set timer task to check connectivity
            self.activation_start_time = time.time()
            self.activation_msg_time = self.activation_start_time
            GObject.timeout_add(ACTIVATION_TIMER_MS, self.check_activation, req_obj)
        else:
            # Failed to create connection from configuration
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)

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
        elif status < 0: # All other failures
            self.send_response(req_obj, MSG_STATUS_ERR_NOCONN)
            return False
        else:
            # Intermediate status, don't send
            return True

    def check_provision(self, req_obj):
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
        # Issue request to Provisoning Manager
        if 'data' in req_obj:
            status = self.prov_manager.start_provisioning(req_obj['data'])
            if self.send_prov_response(req_obj, status):
                # Success, send actualt response
                self.send_response(req_obj, MSG_STATUS_INTERMEDIATE,
                    {'operation' : 'connect'})
                # Set timer task to check status & sent intermediate responses
                self.provision_msg_time = time.time()
                GObject.timeout_add(PROVISION_TIMER_MS, self.check_provision, req_obj)
            else:
                # Failed, response already sent
                pass
        else:
            self.send_response(req_obj, MSG_STATUS_ERR_INVALID)

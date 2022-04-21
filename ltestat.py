"""
ltestat - LTE connection stat reporting service
"""

import dbus
import dbus.exceptions
from syslog import syslog
import json
from gi.repository import GObject as gobject

NM_IFACE = 'org.freedesktop.NetworkManager'
NM_OBJ = '/org/freedesktop/NetworkManager'
NM_DEVICE_IFACE = 'org.freedesktop.NetworkManager.Device'
DBUS_PROP_IFACE = 'org.freedesktop.DBus.Properties'

OFONO_ROOT_PATH = '/'
OFONO_BUS_NAME = 'org.ofono'
OFONO_MANAGER_IFACE = 'org.ofono.Manager'
OFONO_MODEM_IFACE = 'org.ofono.Modem'
OFONO_CONNMAN_IFACE = 'org.ofono.ConnectionManager'
OFONO_CONNECTION_IFACE = 'org.ofono.ConnectionContext'
OFONO_NETREG_IFACE = 'org.ofono.NetworkRegistration'

# Property Maps
#
#    The following lists map the Ofono reported property names
#    to a new name (since some properties like 'Name' for
#    the network operator are too generic), and a flag to indicate
#    whether the change should trigger an update (so we can
#    collect properties like the RSSI without triggering an
#    update too often).

MODEM_PROPERTY_MAP = [
    ('Serial', 'IMEI', False)
]

NETREG_PROPERTY_MAP = [
    ('LocationAreaCode', '', True),
    ('CellId', '', True),
    ('MobileCountryCode', '', True),
    ('MobileNetworkCode' , '', True),
    ('Name', 'OperatorName', True),
    ('Strength', '', False)
]

CONNECTION_PROPERTY_MAP = [
    ('AccessPointName', '', True),
    ('Settings', 'NetworkIpv4', True),
    ('IPv6.Settings', 'NetworkIpv6', True)
]

PROPERTY_CHANGE_DELAY_MS = 15000

class LTEStat():
    """ LTE connection stats reporting service
    """
    def __init__(self, connection_stat_changed_signal):
        self.modem = None
        self.modem_netreg = None
        self.modem_connection = None
        self.connection_status = {}
        self.connection_stats_changed = connection_stat_changed_signal
        self.property_timer_id = None
        try:
            self.bus = dbus.SystemBus()
            self.ofono = dbus.Interface(self.bus.get_object(OFONO_BUS_NAME, OFONO_ROOT_PATH), OFONO_MANAGER_IFACE)
            self.ofono.connect_to_signal('ModemAdded', self.modem_added)
            nm = dbus.Interface(self.bus.get_object(NM_IFACE, NM_OBJ), NM_IFACE)
            eth0_dev_obj = self.bus.get_object(NM_IFACE, nm.GetDeviceByIpIface("eth0"))
            eth0_props = dbus.Interface(eth0_dev_obj, DBUS_PROP_IFACE)
            self.eth0_addr = str(eth0_props.Get(NM_DEVICE_IFACE, "HwAddress"))
        except dbus.DBusException:
            syslog('Ofono not present, LTE status disabled.')

    def collect_properties(self, properties, property_map):
        """ Collect properties from reporting interface into current state
            Returns True if any property in the map reports an update.
        """
        ret = False
        for k in properties.keys():
            for p in property_map:
                if k == p[0]:
                    self.connection_status[p[1] or k] = properties[k]
                    ret = ret or p[2]
        return ret

    def status_update(self):
        """ Send the status report
        """
        # The EdgeIQ ingestor requires that the payload have the
        # MAC address for the eth0 interface to determine the
        # device ID
        payload = { 'eth0' : { 'mac-address' : self.eth0_addr } }
        # Wrap LTE status in "lte" object so that they can be
        # differentiated from NetworkManager status on the same D-Bus signal
        payload['lte'] = self.connection_status
        syslog('Sending LTE connection status via D-Bus: {}'.format(payload))
        self.connection_stats_changed(json.dumps(payload))
        self.property_timer_id = None
        return False # Don't repeat timer

    def schedule_status_update(self):
        """ Schedule or reschedule the satus report
        """
        if self.property_timer_id is not None:
            gobject.source_remove(self.property_timer_id)
        self.property_timer_id = gobject.timeout_add(PROPERTY_CHANGE_DELAY_MS, self.status_update)

    def modem_added(self, object_path, properties):
        """ Modem added signal handler
        """
        self.modem_path = object_path
        self.modem = dbus.Interface(self.bus.get_object(OFONO_BUS_NAME, self.modem_path), OFONO_MODEM_IFACE)
        self.collect_properties(self.modem.GetProperties(), MODEM_PROPERTY_MAP)
        self.modem.connect_to_signal('PropertyChanged', self.modem_prop_changed)

    def modem_prop_changed(self, name, value):
        """ Modem property changed signal handler
        """
        if name == 'Online' and value:
            # Modem has gone online, schedule update
            self.schedule_status_update()
        elif name == 'Interfaces':
            if OFONO_NETREG_IFACE in value and self.modem_netreg is None:
                self.modem_netreg = dbus.Interface(dbus.SystemBus().get_object(OFONO_BUS_NAME,
                    self.modem_path), OFONO_NETREG_IFACE)
                self.collect_properties(self.modem_netreg.GetProperties(), NETREG_PROPERTY_MAP)
                self.modem_netreg.connect_to_signal('PropertyChanged', self.modem_netreg_prop_changed)
            if OFONO_CONNMAN_IFACE in value and self.modem_connection is None:
                connman = dbus.Interface(dbus.SystemBus().get_object(OFONO_BUS_NAME,
                    self.modem_path), OFONO_CONNMAN_IFACE)
                ctx_objs = connman.GetContexts()
                if len(ctx_objs) > 0:
                    self.modem_connection = dbus.Interface(dbus.SystemBus().get_object(OFONO_BUS_NAME,
                        ctx_objs[0][0]), OFONO_CONNECTION_IFACE)
                    self.collect_properties(self.modem_connection.GetProperties(), CONNECTION_PROPERTY_MAP)
                    self.modem_connection.connect_to_signal('PropertyChanged', self.modem_connection_prop_changed)
        else:
            if self.collect_properties({ name : value }, MODEM_PROPERTY_MAP):
                self.schedule_status_update()

    def modem_netreg_prop_changed(self, name, value):
        """ NetworkRegistration property changed signal handler
        """
        if self.collect_properties({ name : value }, NETREG_PROPERTY_MAP):
            self.schedule_status_update()

    def modem_connection_prop_changed(self, name, value):
        """ ConnectionContext property changed signal handler
        """
        if self.collect_properties({ name : value }, CONNECTION_PROPERTY_MAP):
            self.schedule_status_update()

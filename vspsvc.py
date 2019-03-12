"""
Gatt server implementation of virtual serial port using characteristics
"""
import dbus
import threading
import gattsvc
from syslog import syslog, openlog

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    import queue as Queue
else:
    import Queue

UUID_VSP_SVC =         'be98076e-8e8d-11e8-9eb6-529269fb1459'
UUID_VSP_RX =          'be980b1a-8e8d-11e8-9eb6-529269fb1459'
UUID_VSP_TX =          'be980d72-8e8d-11e8-9eb6-529269fb1459'

MAX_TX_LEN = 16

class VirtualSerialPortService(gattsvc.Service):
    """
    Contains the Rx and Tx characteristics
    """
    def __init__(self, bus, index, rx_cb, disc_cb):
        gattsvc.Service.__init__(self, bus, index, UUID_VSP_SVC, True)
        self.add_characteristic(VspRxCharacteristic(bus, 0, self, rx_cb))
        self.vsp_tx = VspTxCharacteristic(bus, 1, self, disc_cb)
        self.add_characteristic(self.vsp_tx)

    def tx(self, message, tx_complete=None):
        self.vsp_tx.tx(message, tx_complete)

    def flush_tx(self):
        self.vsp_tx.flush_tx()

class VspRxCharacteristic(gattsvc.Characteristic):
    """
    Characteristic to receive writes from client
    """
    def __init__(self, bus, index, service, rx_cb):
        gattsvc.Characteristic.__init__(
                self, bus, index,
                UUID_VSP_RX,
                ['write'],
                service)
        self.add_descriptor(
                gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))
        self.rx_cb = rx_cb

    def WriteValue(self, value, options):
        # Convert DBus Array of Bytes to string
        self.rx_cb(''.join([chr(b) for b in value]))
        return True

class VspTxCharacteristic(gattsvc.Characteristic):
    """
    Transfer the file to the client through indications
    """
    def __init__(self, bus, index, service, disc_cb):
        gattsvc.Characteristic.__init__(
                self, bus, index,
                UUID_VSP_TX,
                ['indicate'],
                service)
        self.add_descriptor(
                gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))
        self.tx_mutex = threading.RLock()
        self.tx_queue = Queue.Queue()
        self.tx_remain = None
        self.tx_complete = None
        self.disc_cb = disc_cb

    def send_next_chunk(self):
        # Slice message up into first chunk and remainder
        tx_chunk = None
        tx_complete = None
        self.tx_mutex.acquire()
        if self.tx_remain and len(self.tx_remain) > 0:
            tx_chunk = self.tx_remain[:MAX_TX_LEN]
            self.tx_remain = self.tx_remain[MAX_TX_LEN:]
            if len(self.tx_remain) == 0:
                # Setup callback
                tx_complete = self.tx_complete
                # Get next message from queue
                if not self.tx_queue.empty():
                    self.tx_remain, self.tx_complete = self.tx_queue.get_nowait()
                else:
                    self.tx_remain = None
                    self.tx_complete = None
        self.tx_mutex.release()
        if tx_chunk and len(tx_chunk) > 0:
            # Convert string to array of DBus Bytes & send
            val = [dbus.Byte(b) for b in bytearray(tx_chunk)]
            self.PropertiesChanged(gattsvc.GATT_CHRC_IFACE, { 'Value' : val }, [])
        if tx_complete:
            tx_complete()

    def tx(self, message, tx_complete):
        self.tx_mutex.acquire()
        if self.tx_remain and len(self.tx_remain) > 0:
            # Message in progress, queue for later
            self.tx_queue.put_nowait((message.encode(), tx_complete))
        else:
            # Send immediately
            self.tx_remain = message.encode()
            self.tx_complete = tx_complete
        self.tx_mutex.release()
        self.send_next_chunk()

    def flush_tx(self):
        # Flush any pending Tx data
        self.tx_mutex.acquire()
        self.tx_remain = None
        self.tx_complete = None
        self.tx_mutex.release()

    def StartNotify(self):
        syslog('GATT client subscribed to Tx.')

    def StopNotify(self):
        syslog('GATT client unsubscribed from Tx.')
        self.flush_tx()
        # Notify disconnect via callback
        self.disc_cb()

    def Confirm(self):
        self.send_next_chunk()


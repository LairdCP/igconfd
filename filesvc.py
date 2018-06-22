"""
Gatt server implementation for configuration the Wi-Fi interface over BLE
"""
import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service
import uuid
import array
import time
import gattsvc

from syslog import syslog, openlog

try:
  from gi.repository import GObject
except ImportError:
  import gobject as GObject
import sys

IG_DEFAULT_CON =      'IG-CONN'
NM_IFACE =            'org.freedesktop.NetworkManager'
NM_SETTINGS_IFACE =   'org.freedesktop.NetworkManager.Settings'
NM_SETTINGS_OBJ =     '/org/freedesktop/NetworkManager/Settings'
NM_OBJ =              '/org/freedesktop/NetworkManager'
NM_CONNECTION_IFACE = 'org.freedesktop.NetworkManager.Settings.Connection'

UUID_FILE_SVC =         '98d7336a-b291-4c3e-9b4b-23e94ddaa683'
UUID_FILE_RX =          '970e3804-f1f5-4422-bd3c-c68616c9ddf7'
UUID_FILE_TX =          'ea9c74db-a446-43dc-90ff-a548d42c8dcb'
UUID_FILE_IN =          '1825c4d3-7a89-4e80-a345-1c947588d6d4'
UUID_FILE_OUT =         '946906e6-26a4-4eb1-bf22-16cfc41977bc'
UUID_FILE_NAME =        'f5e2c7ba-a00a-47e8-bab2-f2893e0b0ca4'
UUID_FILE_LENGTH =      'f0aee190-2c29-45d7-8985-6ab079cb6386'

file = None
file_name = ''
file_length = 0

class FileTransferService(gattsvc.Service):
    """
    Contains the Wi-Fi configuration and activation characteristics
    """
    def __init__(self, bus, index):
        gattsvc.Service.__init__(self, bus, index, UUID_FILE_SVC, True)

        self.add_characteristic(FileTransferRxCharacteristic(bus, 0, self))
        self.add_characteristic(FileTransferTxCharacteristic(bus, 1, self))
        self.add_characteristic(FileTransferInCharacteristic(bus, 2, self))
        self.add_characteristic(FileTransferOutCharacteristic(bus, 3, self))
        self.add_characteristic(FileTransferNameCharacteristic(bus, 4, self))
        self.add_characteristic(FileTransferLengthCharacteristic(bus, 5, self))


class FileTransferRxCharacteristic(gattsvc.Characteristic):
    """
    Write part of the file
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
                self, bus, index,
                UUID_FILE_RX,
                ['read', 'write'],
                service)
        self.add_descriptor(
                gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        global file
        self.value = ''.join([chr(byte) for byte in value])
        try:
            file.write(self.value)
        except IOError as e:
            print "I/O error({0}): {1}".format(e.errno, e.strerror)
            sys.exit(1)

class FileTransferTxCharacteristic(gattsvc.Characteristic):
    """
    Transfer the file to the client through a notification
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
                self, bus, index,
                UUID_FILE_TX,
                ['read', 'write'],
                service)

        self.add_descriptor(
                gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        self.value = value

class FileTransferInCharacteristic(gattsvc.Characteristic):
    """
    Write the server to prepare to receive a file
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_FILE_IN,
            ['read', 'write'],
            service)
        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        global file_name, file
        self.value = ''.join([chr(byte) for byte in value])
        try:
            if self.value == '1':
                file = open(file_name, "w")
                syslog('Starting file transfer: %s' % file_name)
            elif self.value == '0':
                syslog('Ending file transfer: %s' % file_name)
                file.close()
        except IOError as e:
            print "I/O error({0}): {1}".format(e.errno, e.strerror)
            sys.exit(1)


class FileTransferOutCharacteristic(gattsvc.Characteristic):
    """
    Start notifying that the server is ready to transfer
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_FILE_OUT,
            ['notify'],
            service)
        self.notifying = False

    def StartNotify(self):
        if self.notifying:
            return

        self.notifying = True
        self.update_file_transfer_out()

    def StopNotify(self):
        if not self.notifying:
            return

        self.notifying = False


class FileTransferNameCharacteristic(gattsvc.Characteristic):
    """
    Write the name of the file to be transferred
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_FILE_NAME,
            ['read', 'write'],
            service)

        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        global file_name
        self.value = ''.join([chr(byte) for byte in value])
        file_name = self.value

class FileTransferLengthCharacteristic(gattsvc.Characteristic):
    """
    Write the length of the file to be transferred
    """
    def __init__(self, bus, index, service):
        gattsvc.Characteristic.__init__(
            self, bus, index,
            UUID_FILE_LENGTH,
            ['read', 'write'],
            service)

        self.add_descriptor(
            gattsvc.CharacteristicUserDescriptionDescriptor(bus, 0, self))

    def ReadValue(self, options):
        return self.value

    def WriteValue(self, value, options):
        global file_length
        self.value = int(value)
        file_length = self.value



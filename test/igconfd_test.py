#!/usr/bin/env python

import sys
import gatt
import threading
import time

try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject
from argparse import ArgumentParser

class AnyDevice(gatt.Device,object):
    def services_resolved(self):
        print('services_resolved')
        super(AnyDevice,self).services_resolved()

    def list_services(self):
        for service in self.services:
            print("[%s]  Service [%s]" % (self.mac_address, service.uuid))
            for characteristic in service.characteristics:
                 props = characteristic._properties.Get('org.bluez.GattCharacteristic1','Flags')
                 print(props)
                 print("[%s]    Characteristic [%s]" % (self.mac_address, characteristic.uuid))

    def read_characteristic(self,characteristic):
        print('read_characteristic')
        wifi_config_service = next(
            s for s in self.services
            if s.uuid == 'f365403e-f94b-4982-9087-716916d90d42')

        wifi_config_characteristic = next(
            c for c in wifi_config_service.characteristics
            if c.uuid == characteristic)

        value = wifi_config_characteristic.read_value()
        print(repr(value))

    def write_characteristic(self,characteristic,value):
        print('write_characteristic')
        wifi_config_service = next(
            s for s in self.services
            if s.uuid == 'f365403e-f94b-4982-9087-716916d90d42')

        wifi_config_characteristic = next(
            c for c in wifi_config_service.characteristics
            if c.uuid == characteristic)

        wifi_config_characteristic.write_value(value)

    def characteristic_value_updated(self, characteristic, value):
        print('characteristic_value_updated')
        print(value)

    def characteristic_write_value_succeeded(self,characteristic):
        print('characteristic_write_value_succeeded')

    def characteristic_read_value_failed(self,characteristic,error):
        print('characteristic_read_value_failed')
        print error

    def read_ssid(self):
        characteristic = self.get_ssid()
        ssid = characteristic.read_value()
        print(ssid)

    def write_ssid(self, value):
        print('write_ssid')
        characteristic = self.get_ssid()
        characteristic.write_value(value)

    def connect_succeeded(self):
        print('connect_succeeded')

    def connect_failed(self):
        print('connect_failed')


def run_command(input_list):
    if input_list[0] == 'exit':
        sys.exit(0)
    if input_list[0] == 'connect':
        device.connect()
    if input_list[0] == 'disconnect':
        device.disconnect()
    if input_list[0] == 'list':
        device.list_services()
    if input_list[0] == 'read':
        device.read_characteristic(input_list[1])
    if input_list[0] == 'write':
        device.write_characteristic(input_list[1],input_list[2])

def test():
    with open('test_commands.txt') as f:
        for line in f:
            input_list = line.split()
            if 'test' in input_list[0]:
                continue
            else:
                run_command(input_list)
            time.sleep(1)

def input():
    while True:
        input = raw_input("gatt# ")
        input = input.strip()
        input_list = input.split()
        if len(input_list[0]) >= 1:
            if input_list[0] == 'test':
                test()
            else:
                run_command(input_list)

arg_parser = ArgumentParser(description="GATT Read Firmware Version Demo")
arg_parser.add_argument('mac_address', help="MAC address of device to connect")
args = arg_parser.parse_args()
manager = gatt.DeviceManager(adapter_name='hci0')
device = AnyDevice(manager=manager, mac_address=args.mac_address)
device.connect()
GObject.threads_init()
thread = threading.Thread(target=manager.run)
thread.start()
input()
manager.stop()


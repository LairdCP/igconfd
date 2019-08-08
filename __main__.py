import dbus, dbus.service, dbus.exceptions
import signal
from syslog import syslog, openlog
from dbus.mainloop.glib import DBusGMainLoop
import systemd
import systemd.daemon
import json

import customsvc
import configsvc

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
    from gi.repository import GLib as glib
else:
    import gobject

DEVICE_IG60 = "Laird IG60"
PROC_DEVICE_TREE_MODEL = '/proc/device-tree/model'

def main():

    DBusGMainLoop(set_as_default=True)

    if PYTHON3:
        mainloop = glib.MainLoop()
    else:
        mainloop = gobject.MainLoop()

    try:
        with open(PROC_DEVICE_TREE_MODEL, "r") as f:
            model = f.read()
            model = model.rstrip('\x00')
            f.close()
    except IOError as e:
        syslog('failed to write value {} to path {}'.format(model, PROC_DEVICE_TREE_MODEL))
        return 1

    manager = None
    if DEVICE_IG60 == model:
        manager = customsvc.CustomService(DEVICE_IG60)
    else:
        manager = configsvc.ConfigurationService(model)

    manager.start()

    # Startup is complete, notify systemd
    systemd.daemon.notify('READY=1')
    mainloop.run()

#
# Run the main loop
#
openlog("IG.ConfService")
syslog("Starting main loop.")
main()

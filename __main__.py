import dbus, dbus.service, dbus.exceptions
import signal
from syslog import syslog, openlog
from dbus.mainloop.glib import DBusGMainLoop
import systemd
import systemd.daemon

import customsvc
import configsvc

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
    from gi.repository import GLib as glib
else:
    import gobject

DEVICE_IG60 = "IG60"
DEVICE_IG60LL = "IG60 LL"
PROC_DEVICE_TREE_MODEL = '/proc/device-tree/model'

def main():
    gobject.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    if PYTHON3:
        mainloop = glib.MainLoop()
    else:
        mainloop = gobject.MainLoop()


    try:
        with open(PROC_DEVICE_TREE_MODEL, "r") as f:
            model = f.read()
            model = model.rstrip()
            f.close()
    except IOError as e:
        syslog('failed to write value {} to path {}'.format(model, PROC_DEVICE_TREE_MODEL))

    manager = None
    if DEVICE_IG60 in model:
        manager = customsvc.CustomService(DEVICE_IG60)
    elif DEVICE_IG60LL in model:
        manager = configsvc.ConfigurationService(DEVICE_IG60LL)
    else:
        exit

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

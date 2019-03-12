import dbus, dbus.service, dbus.exceptions
import signal
from syslog import syslog, openlog
from dbus.mainloop.glib import DBusGMainLoop
import systemd
import systemd.daemon
import devmngr

import sys
PYTHON3 = sys.version_info >= (3, 0)
if PYTHON3:
    from gi.repository import GObject as gobject
    from gi.repository import GLib as glib
else:
    import gobject

def main():
    gobject.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    if PYTHON3:
        mainloop = glib.MainLoop()
    else:
        mainloop = gobject.MainLoop()

    device_manager = devmngr.DeviceManager()

    device_manager.start()

    # Startup is complete, notify systemd
    systemd.daemon.notify('READY=1')
    mainloop.run()

#
# Run the main loop
#
openlog("IG.ConfService")
syslog("Starting main loop.")
main()

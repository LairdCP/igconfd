import dbus, dbus.service, dbus.exceptions
import sys, signal
from syslog import syslog, openlog
from dbus.mainloop.glib import DBusGMainLoop
import systemd
import systemd.daemon
import devmngr

try:
  from gi.repository import GObject
except ImportError:
  import gobject as GObject

def main():
    GObject.threads_init()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

    mainloop = GObject.MainLoop()

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

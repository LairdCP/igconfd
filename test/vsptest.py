import pygatt
import json
import queue as Queue

DEFAULT_ADDR = "c0:ee:40:50:27:03"

MAX_TX_LEN = 16

MSG_TIMEOUT = 10

UUID_VSP_SVC = "be98076e-8e8d-11e8-9eb6-529269fb1459"
UUID_VSP_RX = "be980b1a-8e8d-11e8-9eb6-529269fb1459"
UUID_VSP_TX = "be980d72-8e8d-11e8-9eb6-529269fb1459"

msg_data = None
recvq = Queue.Queue()
conn = None


def tx_cb(handle, value):
    global msg_data
    msg_data = (msg_data or b"") + value
    if msg_data.decode("utf8")[-1] == "}":
        try:
            obj = json.loads(msg_data.decode("utf8"))
            print("Received object.")
            recvq.put(obj)
            msg_data = None
        except ValueError:
            pass
        except KeyError:
            print("Invalid object received")
            msg_data = None


def send_msg(message):
    global conn
    # Slice message up into first chunk and remainder
    tx_chunk = message[:MAX_TX_LEN]
    tx_remain = message[MAX_TX_LEN:]
    while tx_chunk and len(tx_chunk) > 0:
        conn.char_write(
            UUID_VSP_RX, bytearray(tx_chunk.encode("utf8")), wait_for_response=True
        )
        tx_chunk = tx_remain[:MAX_TX_LEN]
        tx_remain = tx_remain[MAX_TX_LEN:]


def send_obj(obj):
    send_msg(json.dumps(obj, separators=(",", ":")))


def send_req(req_type, data=None):
    req_obj = {"id": 1, "version": 1, "type": req_type}
    if data:
        req_obj["data"] = data
    send_obj(req_obj)


def await_resp(timeout):
    try:
        return recvq.get(timeout=timeout)
    except Queue.Empty:
        return None


def connect(addr=DEFAULT_ADDR):
    global conn
    print("Connecting to {}".format(addr))
    conn = adapter.connect(addr, timeout=10)
    conn.subscribe(UUID_VSP_TX, callback=tx_cb, indication=True)


def scan():
    print("Scanning for LE devices...")
    devs = adapter.scan()
    for d in devs:
        print("{}: {}".format(d["address"], d["name"]))


def req_device_id():
    send_req("getDeviceId")
    o = await_resp(5)
    print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))


def req_version():
    send_req("version")
    o = await_resp(5)
    print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))


def req_device_caps():
    send_req("getDeviceCaps")
    o = await_resp(5)
    print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))


def req_aps():
    send_req("getAccessPoints")
    o = await_resp(15)
    print("SSID                              WEP? PSK? EAP?")
    print("================================  ==== ==== ====")
    while o and o["status"] >= 0:
        if "data" in o:
            for ap in o["data"]:
                print(
                    "%-32s %4s %4s %4s"
                    % (
                        ap["ssid"],
                        "Y" if ap["wep"] else "N",
                        "Y" if ap["psk"] else "N",
                        "Y" if ap["eap"] else "N",
                    )
                )
        if o["status"] > 0:
            o = await_resp(10)
        else:
            o = None


def req_connect_ap(connection):
    send_req("connectAP", data=connection)
    o = await_resp(10)
    while o:
        print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))
        o = await_resp(10)


def req_provision(data):
    send_req("provisionURL", data=data)
    o = await_resp(10)
    while o:
        print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))
        o = await_resp(10)


def req_storage_info():
    send_req("getStorageInfo")
    o = await_resp(5)
    print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))


def req_storage_swap():
    send_req("extStorageSwap")
    o = await_resp(10)
    while o:
        print(json.dumps(o, sort_keys=True, indent=4, separators=(",", ": ")))
        o = await_resp(10)


# Start adapter
adapter = pygatt.BGAPIBackend()
adapter.start()

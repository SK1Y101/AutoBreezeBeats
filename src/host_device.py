import socket


def get_device_name() -> str:
    return socket.gethostname()


def get_device_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.0.1", 1))
        return s.getsockname()[0]
    except Exception as e:
        print(f"Error obtaining local IP address: {e}")
        return "127.0.0.1"
    finally:
        s.close()


def get_device_details() -> dict[str, str]:
    return {"name": get_device_name(), "ip": get_device_ip()}

import socket


def find_free_port(preferred: int = 5174, max_tries: int = 20) -> int:
    for port in range(preferred, preferred + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    msg = f"No free port found in range {preferred}-{preferred + max_tries - 1}"
    raise RuntimeError(msg)

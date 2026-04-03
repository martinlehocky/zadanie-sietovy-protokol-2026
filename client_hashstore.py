#!/usr/bin/env python3

import socket
import sys
from pathlib import Path

HOST = "127.0.0.1"
PORT = 9000

HARDCODED_DATA = b"hello world"
HARDCODED_DESCRIPTION = "hardcoded_hello.txt"


def read_header_line(sock: socket.socket) -> str:
    """Read one protocol header line byte-by-byte until '\n'."""
    header = b""
    while not header.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise RuntimeError("Server closed connection while reading header")
        header += chunk
    return header.decode("utf-8", errors="replace").rstrip("\n")


def recv_exact(sock: socket.socket, length: int) -> bytes:
    """Receive exactly `length` bytes or fail if connection closes."""
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(min(4096, length - len(data)))
        if not chunk:
            raise RuntimeError("Server closed connection before full data arrived")
        data.extend(chunk)
    return bytes(data)


def sanitize_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return safe or "downloaded.bin"


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def cmd_list() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        sock.sendall(b"LIST\n")

        header = read_header_line(sock)
        parts = header.split()
        if len(parts) < 3 or parts[0] != "200" or parts[1] != "OK":
            print(f"LIST failed: {header}")
            return 1

        try:
            count = int(parts[2])
        except ValueError:
            print(f"Invalid LIST count in response: {header}")
            return 1

        print(f"LIST OK, {count} item(s):")
        for _ in range(count):
            line = read_header_line(sock)
            item_parts = line.split(maxsplit=1)
            if not item_parts:
                print("<invalid empty item line>")
                continue
            file_hash = item_parts[0]
            description = item_parts[1] if len(item_parts) > 1 else ""
            print(f"{file_hash} {description}".rstrip())

    return 0


def cmd_get(file_hash: str, output_name: str | None = None) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        sock.sendall(f"GET {file_hash}\n".encode("utf-8"))

        header = read_header_line(sock)
        if not header.startswith("200 "):
            print(f"GET failed: {header}")
            return 1

        # 200 OK <length> <description-with-possible-spaces>
        parts = header.split(maxsplit=3)
        if len(parts) < 4 or parts[1] != "OK":
            print(f"Invalid GET header: {header}")
            return 1

        try:
            length = int(parts[2])
        except ValueError:
            print(f"Invalid GET length in header: {header}")
            return 1

        description = parts[3]
        data = recv_exact(sock, length)

        if output_name:
            out_path = Path(output_name)
        else:
            out_path = script_dir() / f"down_{sanitize_filename(description)}"

        out_path.write_bytes(data)
        print(f"Downloaded {length} byte(s) to: {out_path}")
    return 0


def upload_bytes(data: bytes, description: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))

        header = f"UPLOAD {len(data)} {description}\n".encode("utf-8")
        # Header and payload are sent on the same connection.
        sock.sendall(header)
        sock.sendall(data)

        response = read_header_line(sock)
        parts = response.split()
        if len(parts) >= 3 and parts[0] == "200" and parts[1] == "STORED":
            print(f"Upload successful, hash: {parts[2]}")
            return 0
        if len(parts) >= 3 and parts[0] == "409" and parts[1] == "HASH_EXISTS":
            print(f"Upload skipped, hash already exists: {parts[2]}")
            return 0

        print(f"UPLOAD failed: {response}")
        return 1


def cmd_upload_file(file_path: str, description: str) -> int:
    path = Path(file_path)
    if not path.is_file():
        print(f"File not found: {file_path}")
        return 1
    data = path.read_bytes()
    return upload_bytes(data, description)


def cmd_upload_hardcoded() -> int:
    return upload_bytes(HARDCODED_DATA, HARDCODED_DESCRIPTION)


def cmd_upload_stdin(description: str) -> int:
    data = sys.stdin.buffer.read()
    return upload_bytes(data, description)


def cmd_delete(file_hash: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        sock.sendall(f"DELETE {file_hash}\n".encode("utf-8"))

        response = read_header_line(sock)
        code = response.split(maxsplit=1)[0] if response else ""

        if code == "200":
            print("DELETE successful")
            return 0
        if code == "404":
            print("DELETE failed: NOT_FOUND")
            return 1
        if code == "400":
            print("DELETE failed: BAD_REQUEST")
            return 1
        if code == "500":
            print("DELETE failed: SERVER_ERROR")
            return 1

        print(f"DELETE failed: {response}")
        return 1


def print_usage() -> None:
    print("Usage:")
    print("  python client_hashstore.py list")
    print("  python client_hashstore.py get <hash> [output_file]")
    print("  python client_hashstore.py upload <file> <description>")
    print("  python client_hashstore.py upload-hardcoded")
    print("  python client_hashstore.py upload-stdin <description>")
    print("  python client_hashstore.py delete <hash>")


def main() -> int:
    try:
        if len(sys.argv) < 2:
            print_usage()
            return 1

        cmd = sys.argv[1]

        if cmd == "list":
            if len(sys.argv) != 2:
                print_usage()
                return 1
            return cmd_list()

        if cmd == "get":
            if len(sys.argv) not in (3, 4):
                print_usage()
                return 1
            file_hash = sys.argv[2]
            output = sys.argv[3] if len(sys.argv) == 4 else None
            return cmd_get(file_hash, output)

        if cmd == "upload":
            if len(sys.argv) < 4:
                print_usage()
                return 1
            file_path = sys.argv[2]
            description = " ".join(sys.argv[3:])
            return cmd_upload_file(file_path, description)

        if cmd == "upload-hardcoded":
            if len(sys.argv) != 2:
                print_usage()
                return 1
            return cmd_upload_hardcoded()

        if cmd == "upload-stdin":
            if len(sys.argv) < 3:
                print_usage()
                return 1
            description = " ".join(sys.argv[2:])
            return cmd_upload_stdin(description)

        if cmd == "delete":
            if len(sys.argv) != 3:
                print_usage()
                return 1
            return cmd_delete(sys.argv[2])

        print_usage()
        return 1

    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

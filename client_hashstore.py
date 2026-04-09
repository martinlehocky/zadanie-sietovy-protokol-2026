#!/usr/bin/env python3

import socket
import sys
import shlex
from pathlib import Path

HOST = "127.0.0.1"
PORT = 9000

HARDCODED_DATA = b"hello world"
HARDCODED_DESCRIPTION = "hardcoded_hello.txt"


def read_header_line(sock: socket.socket) -> str:
    header = b""
    while not header.endswith(b"\n"):
        chunk = sock.recv(1)
        if not chunk:
            raise RuntimeError("Server closed connection while reading header")
        header += chunk
    return header.decode("utf-8", errors="replace").rstrip("\n")


def recv_exact(sock: socket.socket, length: int) -> bytes:
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
            print(f"Zlyhal príkaz LIST: {header}")
            return 1

        try:
            count = int(parts[2])
        except ValueError:
            print(f"Neplatný počet v odpovedi LIST: {header}")
            return 1

        print(f"LIST OK, počet položiek: {count}")
        for _ in range(count):
            line = read_header_line(sock)
            item_parts = line.split(maxsplit=1)
            if not item_parts:
                print("<neplatný prázdny riadok položky>")
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
            print(f"Zlyhal príkaz GET: {header}")
            return 1

        parts = header.split(maxsplit=3)
        if len(parts) < 4 or parts[1] != "OK":
            print(f"Neplatná hlavička GET: {header}")
            return 1

        try:
            length = int(parts[2])
        except ValueError:
            print(f"Neplatná dĺžka v hlavičke GET: {header}")
            return 1

        description = parts[3]
        data = recv_exact(sock, length)

        if output_name:
            out_path = Path(output_name)
            if not out_path.name.startswith("down_"):
                out_path = out_path.with_name(f"down_{out_path.name}")
        else:
            out_path = script_dir() / f"down_{sanitize_filename(description)}"

        out_path.write_bytes(data)
        print(f"Stiahnutých {length} bajtov do: {out_path}")
    return 0


def upload_bytes(data: bytes, description: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))

        header = f"UPLOAD {len(data)} {description}\n".encode("utf-8")

        sock.sendall(header)
        sock.sendall(data)

        response = read_header_line(sock)
        parts = response.split()
        if len(parts) >= 3 and parts[0] == "200" and parts[1] == "STORED":
            print(f"Upload bol úspešný, hash: {parts[2]}")
            return 0
        if len(parts) >= 3 and parts[0] == "409" and parts[1] == "HASH_EXISTS":
            print(f"Upload preskočený, hash už existuje: {parts[2]}")
            return 0

        print(f"Zlyhal príkaz UPLOAD: {response}")
        return 1


def cmd_upload_file(file_path: str, description: str) -> int:
    path = Path(file_path)
    if not path.is_file():
        print(f"Súbor nebol nájdený: {file_path}")
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
            print("DELETE prebehol úspešne")
            return 0
        if code == "404":
            print("Zlyhal príkaz DELETE: NOT_FOUND (súbor sa nenašiel)")
            return 1
        if code == "400":
            print("Zlyhal príkaz DELETE: BAD_REQUEST (neplatná požiadavka)")
            return 1
        if code == "500":
            print("Zlyhal príkaz DELETE: SERVER_ERROR (chyba servera)")
            return 1

        print(f"Zlyhal príkaz DELETE: {response}")
        return 1


def print_usage() -> None:
    print("Použitie:")
    print("  python client_hashstore.py")
    print("  python client_hashstore.py list")
    print("  python client_hashstore.py get <hash> [output_file]")
    print("  python client_hashstore.py upload <file> <description>")
    print("  python client_hashstore.py upload-hardcoded")
    print("  python client_hashstore.py upload-stdin <description>")
    print("  python client_hashstore.py delete <hash>")


def print_interactive_help() -> None:
    print("Dostupné príkazy:")
    print("  list")
    print("  get <hash> [output_file]")
    print("  upload <file> <description>")
    print("  upload-hardcoded")
    print("  delete <hash>")
    print("  help")
    print("  exit | quit")


def run_command(args: list[str], interactive: bool = False) -> int:
    show_help = print_interactive_help if interactive else print_usage

    if not args:
        show_help()
        return 1

    cmd = args[0]

    if cmd == "list":
        if len(args) != 1:
            show_help()
            return 1
        return cmd_list()

    if cmd == "get":
        if len(args) not in (2, 3):
            show_help()
            return 1
        file_hash = args[1]
        output = args[2] if len(args) == 3 else None
        return cmd_get(file_hash, output)

    if cmd == "upload":
        if len(args) < 3:
            show_help()
            return 1
        file_path = args[1]
        description = " ".join(args[2:])
        return cmd_upload_file(file_path, description)

    if cmd == "upload-hardcoded":
        if len(args) != 1:
            show_help()
            return 1
        return cmd_upload_hardcoded()

    if cmd == "upload-stdin":
        if interactive:
            print("Príkaz upload-stdin nie je dostupný v interaktívnom režime.")
            print("Použite jednorazový režim: python client_hashstore.py upload-stdin <description>")
            return 1
        if len(args) < 2:
            show_help()
            return 1
        description = " ".join(args[1:])
        return cmd_upload_stdin(description)

    if cmd == "delete":
        if len(args) != 2:
            show_help()
            return 1
        return cmd_delete(args[1])

    show_help()
    return 1


def interactive_loop() -> int:
    print("Zadajte 'help' pre pomoc, 'exit' alebo 'quit' pre ukončenie.")
    while True:
        try:
            raw = input("hashstore> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue

        if not raw:
            continue

        if raw in ("exit", "quit"):
            return 0

        if raw == "help":
            print_interactive_help()
            continue

        try:
            args = shlex.split(raw)
        except ValueError as exc:
            print(f"Neplatný vstup: {exc}")
            continue

        try:
            run_command(args, interactive=True)
        except Exception as exc:
            print(f"Chyba: {exc}")


def main() -> int:
    try:
        if len(sys.argv) == 1:
            return interactive_loop()
        return run_command(sys.argv[1:], interactive=False)

    except Exception as exc:
        print(f"Chyba: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

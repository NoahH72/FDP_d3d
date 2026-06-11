#!/usr/bin/env python3
"""
Single-threaded HTTP CONNECT proxy for routing compute-node HTTPS traffic
through a Polaris login node.

Uses asyncio with synchronous DNS resolution to avoid spawning ANY threads,
staying within the Polaris login node cgroup PID limit (128).

Usage (login node):
    nohup python3 https_proxy.py > /eagle/fusiondl_aesp/harrisn/fdp/proxy.log 2>&1 &

From compute node PBS job:
    export ALL_PROXY=http://polaris-login-04:18443
    export all_proxy=$ALL_PROXY
    fdp run python my_script.py
"""

import argparse
import asyncio
import os
import socket
import sys
import time

BUFFER_SIZE = 65536
CONNECT_TIMEOUT = 30

_active_conns = 0
_total_conns = 0
_dns_cache = {}


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] {}".format(ts, msg), flush=True)


def _resolve_sync(host, port):
    """Synchronous DNS resolution with caching. No threads created."""
    key = (host, port)
    cached = _dns_cache.get(key)
    if cached and (time.monotonic() - cached[1]) < 300:
        return cached[0]
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise OSError("DNS resolution failed for {}:{}".format(host, port))
    addr = infos[0][4]
    _dns_cache[key] = (addr, time.monotonic())
    return addr


def _make_connected_socket(host, port):
    """Create and connect a socket synchronously. Zero threads."""
    addr = _resolve_sync(host, port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    sock.connect(addr)
    sock.setblocking(False)
    return sock


if sys.version_info >= (3, 7):
    async def _open_connection_no_threads(host, port, loop):
        sock = _make_connected_socket(host, port)
        return await asyncio.open_connection(sock=sock)
else:
    async def _open_connection_no_threads(host, port, loop):
        sock = _make_connected_socket(host, port)
        return await asyncio.open_connection(sock=sock, loop=loop)


async def _relay(reader, writer, label=""):
    try:
        while True:
            data = await reader.read(BUFFER_SIZE)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def handle_client(client_reader, client_writer, loop):
    global _active_conns, _total_conns
    _active_conns += 1
    _total_conns += 1
    seq = _total_conns
    active = _active_conns

    peername = client_writer.get_extra_info("peername", ("?", 0))
    remote_writer = None

    try:
        raw = b""
        while b"\r\n\r\n" not in raw and len(raw) < 8192:
            chunk = await asyncio.wait_for(client_reader.read(4096), timeout=10)
            if not chunk:
                return
            raw += chunk

        first_line = raw.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first_line.split()
        if len(parts) < 3 or parts[0] != "CONNECT":
            client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            await client_writer.drain()
            return

        host_port = parts[1]
        if ":" in host_port:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        else:
            host = host_port
            port = 443

        _log("#{} CONNECT {} from {}  (active={})".format(seq, host_port, peername[0], active))

        try:
            remote_reader, remote_writer = await _open_connection_no_threads(host, port, loop)
        except Exception as e:
            _log("#{} FAIL {}: {}".format(seq, host_port, e))
            client_writer.write("HTTP/1.1 502 Bad Gateway\r\n\r\n{}".format(e).encode())
            await client_writer.drain()
            return

        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()

        await asyncio.gather(
            _relay(client_reader, remote_writer, "#{} c->r".format(seq)),
            _relay(remote_reader, client_writer, "#{} r->c".format(seq)),
        )

    except asyncio.TimeoutError:
        _log("#{} TIMEOUT from {}".format(seq, peername[0]))
    except (ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:
        _log("#{} ERR: {}".format(seq, e))
    finally:
        _active_conns -= 1
        for w in (client_writer, remote_writer):
            if w is not None:
                try:
                    w.close()
                except Exception:
                    pass


ADDR_FILE = "/eagle/fusiondl_aesp/harrisn/fdp/.proxy_addr"


def write_addr_file(hostname, port):
    try:
        with open(ADDR_FILE, "w") as f:
            f.write("{}:{}\n".format(hostname, port))
        _log("Proxy address written to {}".format(ADDR_FILE))
    except Exception as e:
        _log("Warning: could not write {}: {}".format(ADDR_FILE, e))


def remove_addr_file():
    try:
        os.unlink(ADDR_FILE)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="HTTP CONNECT proxy (asyncio, zero threads)")
    parser.add_argument("--port", type=int, default=18443)
    parser.add_argument("--bind", default="0.0.0.0")
    args = parser.parse_args()

    hostname = socket.gethostname().split(".")[0]

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _on_client(reader, writer):
        asyncio.ensure_future(handle_client(reader, writer, loop), loop=loop)

    if sys.version_info >= (3, 7):
        coro = asyncio.start_server(_on_client, args.bind, args.port)
    else:
        coro = asyncio.start_server(_on_client, args.bind, args.port, loop=loop)

    server = loop.run_until_complete(coro)
    _log("HTTPS CONNECT proxy on {}:{} (hostname: {}, asyncio, zero-thread DNS)".format(
        args.bind, args.port, hostname))
    write_addr_file(hostname, args.port)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        _log("Shutting down proxy")
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())
        remove_addr_file()
        loop.close()


if __name__ == "__main__":
    main()

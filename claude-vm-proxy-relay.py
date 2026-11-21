#!/usr/bin/env python3
"""TCP relay bound to the UTM bridge IP only.

Listens on 192.168.64.1:10808 (the host side of the VM-only bridge) and
forwards raw TCP to the local xray mixed inbound at 127.0.0.1:10808.
The hotspot/LAN cannot reach 192.168.64.1, so this does not expose the
proxy beyond the VM network.
"""
import asyncio

LISTEN_HOST = "192.168.64.1"
LISTEN_PORT = 10808
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 10808


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        up_reader, up_writer = await asyncio.open_connection(UPSTREAM_HOST, UPSTREAM_PORT)
    except Exception:
        writer.close()
        return
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


async def main() -> None:
    while True:
        try:
            server = await asyncio.start_server(handle, LISTEN_HOST, LISTEN_PORT)
            break
        except OSError as exc:
            print(f"bind {LISTEN_HOST}:{LISTEN_PORT} failed: {exc}; retrying in 5s", flush=True)
            await asyncio.sleep(5)
    print(f"relay listening on {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM_HOST}:{UPSTREAM_PORT}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

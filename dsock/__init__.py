# Copyright (C) 2024 Bob Carroll <bob.carroll@alum.rit.edu>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import asyncio
import logging

from dsock.pipe import Pipe
from dsock.socket import PipeSocket, SocketChannel

buffer_size = Pipe.BUFFER_SIZE
reuse_handles = True


class DatagramProtocol(asyncio.DatagramProtocol):

    def __init__(self, channel: SocketChannel) -> None:
        """
        A datagram forwarder for pipe sockets.
        """
        self.channel = channel
        self.transport = None
        self._addr = None

    def connection_made(self, transport):
        """
        Callback for when the datagram endpoint is created.
        """
        self.transport = transport
        self.channel.on_data_received = self.channel_data_received

    def connection_lost(self, exc):
        """
        Callback for when the datagram endpoint closes.
        """
        self.channel.close()

    def datagram_received(self, data, addr):
        """
        Callback for when a datagram is received.
        """
        self._addr = addr
        asyncio.ensure_future(self.channel.send(data))

    async def channel_data_received(self, data: bytes):
        """
        Callback for when data data is received on the channel.
        """
        self.transport.sendto(data, self._addr)


async def datagram_channel_open(channel: SocketChannel):
    """
    Callback invoked when a remote channel is opened.
    """
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DatagramProtocol(channel), remote_addr=(channel.address, channel.port))
    logging.info(f'server: datagram channel open to {channel.address}:{channel.port}')


async def datagram_channel_close(channel: SocketChannel):
    """
    Callback invoked when a remote channel is closed.
    """
    logging.info(f'server: channel {channel.number} closed')


async def stream_channel_wait(channel: SocketChannel, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter) -> None:
    """
    Closes the channel when the reader is at EOF.
    """
    while not reader.at_eof():
        await asyncio.sleep(0.1)

    await channel.close()
    writer.close()
    await writer.wait_closed()
    logging.info(f'server: channel {channel.number} closed')


async def stream_channel_open(channel: SocketChannel) -> None:
    """
    Callback invoked when a remote channel is opened.
    """
    try:
        reader, writer = await asyncio.open_connection(
                channel.address, channel.port, limit=buffer_size)
    except ConnectionError:
        logging.error(f'server: error connecting to {channel.address}:{channel.port}')
        raise

    logging.info(f'server: connection established to {channel.address}:{channel.port}')
    channel.on_data_received = lambda x: stream_channel_data_received(x, writer)
    asyncio.ensure_future(stream_data_loop(reader, channel))
    asyncio.ensure_future(stream_channel_wait(channel, reader, writer))


async def stream_channel_close(channel: SocketChannel) -> None:
    """
    Callback invoked when a remote channel is closed.
    """
    logging.info(f'server: channel {channel.number} closed')


async def stream_channel_data_received(data: bytes, writer: asyncio.StreamWriter) -> None:
    """
    Callback invoked when data is received on a channel.
    """
    writer.write(data)
    await writer.drain()


async def stream_data_loop(reader: asyncio.StreamReader, channel: SocketChannel) -> None:
    """
    Continuously reads data from the stream reader and sends it over the channel.
    """
    logging.debug(f'server: connection data loop started on channel {channel.number}')

    while channel.is_open:
        try:
            data = await reader.read(buffer_size)
        except (BrokenPipeError, ConnectionError):
            break

        try:
            await channel.send(data)
        except ConnectionError:
            break

        await asyncio.sleep(0.005)

    logging.debug(f'server: connection data loop ended on channel {channel.number}')


async def stream_connection_accepted(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                                     psocket: PipeSocket, remote_addr: str,
                                     remote_port: int) -> None:
    """
    Callback invoked when a connection is accepted.
    """
    logging.info(f'server: connection accepted from {writer.get_extra_info("peername")}')
    try:
        channel = await psocket.open_channel(remote_addr, remote_port)
        channel.on_data_received = lambda x: stream_channel_data_received(x, writer)
    except ConnectionError:
        logging.error(f'server: failed to open channel to {remote_addr}:{remote_port}')
        writer.close()
        await writer.wait_closed()
        return

    asyncio.ensure_future(stream_data_loop(reader, SocketChannel(psocket, channel)))

    while not reader.at_eof() and channel.is_open:
        await asyncio.sleep(0.1)

    await psocket.close_channel(channel)

    try:
        writer.close()
        await writer.wait_closed()
    except ConnectionError:
        pass

    logging.info(f'server: connection closed from {writer.get_extra_info("peername")}')


async def channel_open(channel: SocketChannel) -> None:
    """
    Callback invoked when a remote channel is opened.
    """
    if channel.is_datagram:
        await datagram_channel_open(channel)
    else:
        await stream_channel_open(channel)


async def channel_close(channel: SocketChannel) -> None:
    """
    Callback invoked when a remote channel is closed.
    """
    if channel.is_datagram:
        await datagram_channel_close(channel)
    else:
        await stream_channel_close(channel)


def create_pipe_socket(path: str, server: bool = False) -> PipeSocket:
    """
    Creates a new pipe socket.
    """
    psocket = PipeSocket(Pipe(path, server=server, reuse_handles=reuse_handles))
    psocket.on_remote_open = lambda x: channel_open(SocketChannel(psocket, x))
    psocket.on_remote_close = lambda x: channel_close(SocketChannel(psocket, x))

    logging.debug(f'socket: created pipe socket for {path}')
    return psocket


async def start_pipe_server(path: str) -> PipeSocket:
    """
    Starts a server that listens for incoming pipe connections.
    """
    psocket = create_pipe_socket(path, server=True)
    await psocket.start()
    await asyncio.Event().wait()


async def start_stream_listener(listen_addr: str, listen_port: int, remote_addr: str,
                                remote_port: int, pipe_path: str) -> None:
    """
    Starts a stream server that listens for incoming connections.
    """
    psocket = create_pipe_socket(pipe_path)
    await psocket.start()

    server = await asyncio.start_server(
            lambda r, w: stream_connection_accepted(r, w, psocket, remote_addr, remote_port),
            listen_addr, listen_port, limit=buffer_size)

    logging.info(f'server: listening on {listen_addr}:{listen_port}')
    async with server:
        await server.serve_forever()


async def start_datagram_listener(listen_addr: str, listen_port: int, remote_addr: str,
                                  remote_port: int, pipe_path: str) -> None:
    """
    Starts a datagram server that listens for incoming messages.
    """
    psocket = create_pipe_socket(pipe_path)
    await psocket.start()

    loop = asyncio.get_running_loop()
    forever = loop.create_future()

    try:
        channel = await psocket.open_channel(remote_addr, remote_port, PipeSocket.TRANSPORT_UDP)
    except Exception as ex:
        logging.error(f'server: channel open returned an error: {str(ex)}')
        return

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DatagramProtocol(SocketChannel(psocket, channel)),
        local_addr=(listen_addr, listen_port))

    await forever

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
from typing import Iterator, Callable

from .pipe import Pipe
from .protocol import PacketProtocol, Packet
from .channel import Channel, ChannelEventCallback, nop


class TransmitQueue(object):

    def __init__(self) -> None:
        """
        A thread-safe queue for transmitting packets.
        """
        self._queue: list[Packet] = []
        self._mtx = asyncio.Lock()

    def __iter__(self) -> Iterator[Packet]:
        """
        Returns an iterator for the queue.
        """
        return iter(self._queue)

    def __len__(self) -> int:
        """
        Returns the number of packets in the queue.
        """
        return len(self._queue)

    def append(self, packet: Packet) -> None:
        """
        Appends a packet to the queue.
        """
        self._queue.append(packet)
        logging.debug(f'queue: append {packet}, count={len(self._queue)}')

    def insert(self, packet: Packet) -> None:
        """
        Inserts a packet at the beginning of the queue.
        """
        self._queue.insert(0, packet)
        logging.debug(f'queue: insert {packet}, count={len(self._queue)}')

    def peek(self) -> Packet | None:
        """
        Returns the first packet in the queue without removing it.
        """
        return self._queue[0] if len(self._queue) > 0 else None

    def pop(self, index: int = 0) -> Packet:
        """
        Removes and return the packet at the specified index.
        """
        packet = self._queue.pop(index)
        logging.debug(f'queue: pop {packet}, count={len(self._queue)}')
        return packet

    def drop(self, func: Callable[[Packet], bool]) -> None:
        """
        Removes packets from the queue that match the given predicate.
        """
        logging.debug('queue: dropping packets from closed channel')
        self._queue[:] = [packet for packet in self._queue if not func(packet)]

    def lock(self) -> asyncio.Lock:
        """
        Returns the lock object for the queue.
        """
        return self._mtx


class PipeSocket(object):

    SEND_LOOP_FREQ: float = 0.005
    RECV_LOOP_FREQ: float = 0.001

    TRANSPORT_TCP: int = 0
    TRANSPORT_UDP: int = 1

    def __init__(self, pipe: Pipe) -> None:
        """
        A socket-like interface for sending and receiving data over a pipe.
        """
        self._pipe = pipe
        self._protocol = PacketProtocol(packet_size=Pipe.BUFFER_SIZE)
        self._recv_loop_task: asyncio.Task = None
        self._send_loop_task: asyncio.Task = None
        self._queue = TransmitQueue()
        self.on_remote_open: ChannelEventCallback = nop
        self.on_remote_close: ChannelEventCallback = nop

    async def start(self) -> None:
        """
        Starts the socket's send and receive loops.
        """
        self._recv_loop_task = asyncio.create_task(self._recv_loop())
        self._send_loop_task = asyncio.create_task(self._send_loop())

    async def open_channel(self, addr: str, port: int, transport: int = TRANSPORT_TCP) -> Channel:
        """
        Opens a channel to the specified address and port.
        """
        channel = Channel(self._protocol.allocate_channel(), addr, port)
        logging.debug(f'socket: opening channel {channel.number} to '
                      f'{channel.address}:{channel.port}')
        packet = self._protocol.open_channel(channel, transport == PipeSocket.TRANSPORT_UDP)

        async with self._queue.lock():
            self._queue.append(packet)

        await channel.ready.wait()

        if channel.state == Channel.STATE_CLOSED:
            raise ConnectionError(f'Channel {channel.number} open refused by peer')

        logging.debug(f'socket: channel {channel.number} opened')
        channel.state = Channel.STATE_OPEN
        return channel

    async def close_channel(self, channel: Channel) -> None:
        """
        Closes the specified channel.
        """
        logging.debug(f'socket: closing channel {channel.number}')

        if not channel.is_open:
            return

        channel.state = Channel.STATE_CLOSING
        packet = self._protocol.close_channel(channel)
        channel.ready.clear()

        async with self._queue.lock():
            self._queue.append(packet)

        await channel.ready.wait()

        async with self._queue.lock():
            self._queue.drop(lambda x: x.channel.number == channel.number)

        channel.state = Channel.STATE_CLOSED
        logging.debug(f'socket: channel {channel.number} closed')
        self._protocol.free_channel(channel)

    async def send(self, channel: Channel, data: bytes) -> None:
        """
        Sends data over the specified channel.
        """
        if not channel.is_open:
            raise ConnectionError(f'Channel {channel.number} is not open')

        async with self._queue.lock():
            for packet in self._protocol.pack(channel, data):
                self._queue.append(packet)

    async def _send_loop(self) -> None:
        """
        Continuously sends packets from the queue.
        """
        logging.info('socket: send loop started')

        while not self._send_loop_task.cancelled():
            await asyncio.sleep(self.SEND_LOOP_FREQ)

            async with self._queue.lock():
                packet = self._queue.peek()

                if packet:
                    logging.debug(f'socket: dequeuing packet for transmission: {packet}')
                    await self._protocol.send(self._pipe.write, packet)
                    self._queue.pop()

    async def _cancel_refused_channel(self, packet: Packet) -> None:
        """
        Cancels a channel opening that was refused by the remote peer.
        """
        logging.warn('socket: channel open refused by peer')
        packet.channel.state = Channel.STATE_CLOSED
        packet.channel.ready.set()

    async def _on_remote_open(self, syn: Packet) -> Packet:
        """
        Handles a channel open event from the remote peer.
        """
        ack = self._protocol.channel_setup(syn)

        try:
            await self.on_remote_open(ack.channel)
            ack.channel.state = Channel.STATE_OPEN
        except Exception:
            ack = self._protocol.channel_refused(ack)

        return ack

    def _on_remote_close(self, rst: Packet) -> Packet:
        """
        Handles a channel close event from the remote peer.
        """
        ack = self._protocol.channel_reset(rst)
        asyncio.ensure_future(self.on_remote_close(ack.channel))
        return ack

    def _on_data_received(self, packet: Packet) -> None:
        """
        Handles a data received event from the remote peer.
        """
        data = self._protocol.unpack(packet)
        asyncio.ensure_future(packet.channel.on_data_received(data))

    async def _recv_loop(self) -> None:
        """
        Continuously receives packets from the pipe.
        """
        logging.info('socket: receive loop started')

        while not self._recv_loop_task.cancelled():
            await asyncio.sleep(self.RECV_LOOP_FREQ)

            packet = await self._protocol.recv(self._pipe.read)
            if packet is None:
                continue

            logging.debug(f'socket: received packet: {packet}')

            if packet.is_refused:
                await self._cancel_refused_channel(packet)
            elif packet.is_setup:
                self._queue.append(await self._on_remote_open(packet))
            elif packet.is_reset:
                self._queue.append(self._on_remote_close(packet))
            elif packet.is_data:
                self._on_data_received(packet)
            else:
                logging.warning(f'socket: unknown packet type: {packet}')


class SocketChannel(object):

    def __init__(self, socket: PipeSocket, channel: Channel) -> None:
        """
        Convenience wrapper for a channel object with send and close methods.
        """
        self._socket = socket
        self._channel = channel

    @property
    def number(self) -> int:
        """
        Returns the channel number.
        """
        return self._channel.number

    @property
    def address(self) -> str:
        """
        Returns the channel IP address.
        """
        return self._channel.address

    @property
    def port(self) -> int:
        """
        Returns the channel port number.
        """
        return self._channel.port

    @property
    def on_data_received(self) -> ChannelEventCallback:
        """
        A callback that is invoked when data is received on the channel.
        """
        return self._channel.on_data_received

    @on_data_received.setter
    def on_data_received(self, callback: ChannelEventCallback):
        """
        Sets the callback that is invoked when data is received on the channel.
        """
        self._channel.on_data_received = callback

    @property
    def is_open(self) -> bool:
        """
        Returns whether the channel is open.
        """
        return self._channel.is_open

    @property
    def is_datagram(self) -> bool:
        """
        Returns whether the channel handles datagram packets.
        """
        return self._channel.is_datagram

    async def send(self, data: bytes) -> None:
        """
        Sends data over the channel.
        """
        await self._socket.send(self._channel, data)

    async def close(self) -> None:
        """
        Closes the channel.
        """
        await self._socket.close_channel(self._channel)

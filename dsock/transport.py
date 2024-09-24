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
from ipaddress import ip_address, IPv4Address, IPv6Address
from typing import Self, Iterator, Callable


class Flags(object):

    def __init__(self) -> None:
        """
        Bitfield for transmission options.
        """
        # segment contains an acknowledgement
        self.ack: bool = False
        # segment contains the last chunk in the payload
        self.fin: bool = False
        # segment contains an IPv6 address
        self.ip6: bool = False
        # segment contains a channel reset
        self.rst: bool = False
        # segment contains a channel setup
        self.syn: bool = False

    def encode(self) -> bytes:
        """
        Encodes the flags into a single byte.
        """
        buf = 0
        buf |= self.ack << 4
        buf |= self.rst << 3
        buf |= self.fin << 2
        buf |= self.syn << 1
        buf |= self.ip6
        return buf.to_bytes(1)

    def decode(self, buf: bytes) -> None:
        """
        Decodes the flags from a single byte.
        """
        flags = int.from_bytes(buf)
        self.ack = bool(flags & 0b00010000)
        self.rst = bool(flags & 0b00001000)
        self.fin = bool(flags & 0b00000100)
        self.syn = bool(flags & 0b00000010)
        self.ip6 = bool(flags & 0b00000001)


class Header(object):

    MAGIC: bytes = b'\x07\xf0\x28'
    LENGTH: int = 32

    def __init__(self) -> None:
        """
        Segment header containing transmission metadata.
        """
        # IP Address
        self.address: IPv4Address | IPv6Address = None
        # channel number
        self.channel: int = 0
        # payload length in bytes
        self.data_length: int = 0
        # transmission flags
        self.flags: Flags = Flags()
        # network port
        self.port: int = 0
        # reserved byte for future use
        self.reserved: bytes = b'\x00'
        # segment sequence number
        self.sequence: int = 0
        # protocol version
        self.version: bytes = b'\x01'

    def _encode_addr(self) -> bytes:
        """
        Encodes the IP address into bytes.
        """
        if not self.address:
            return b'\x00' * 16
        elif self.address.version == 6:
            return self.address.packed
        else:
            return (b'\x00' * 12) + self.address.packed

    def _decode_addr(self, buf: bytes) -> IPv4Address | IPv6Address:
        """
        Decodes the IP address from bytes.
        """
        if self.flags.ip6:
            return IPv6Address(buf[:16])
        else:
            return IPv4Address(buf[12:16])

    def encode(self) -> bytes:
        """
        Encodes the header into bytes.
        """
        buf = bytearray(self.MAGIC)
        buf += self.version
        buf += self.channel.to_bytes(2)
        buf += self.reserved
        buf += self.flags.encode()
        buf += self._encode_addr()
        buf += self.port.to_bytes(2)
        buf += self.sequence.to_bytes(2)
        buf += self.data_length.to_bytes(4)
        return buf

    @staticmethod
    def decode(buf: bytes) -> Self:
        """
        Decodes the header from bytes.
        """
        if buf[:3] != Header.MAGIC:
            raise ValueError('Bad magic number')

        header = Header()
        header.version = buf[3:4]
        header.channel = int.from_bytes(buf[4:6])
        header.reserved = buf[6:7]
        header.flags.decode(buf[7:8])
        header.address = header._decode_addr(buf[8:24])
        header.port = int.from_bytes(buf[24:26])
        header.sequence = int.from_bytes(buf[26:28])
        header.data_length = int.from_bytes(buf[28:32])
        return header


class Segment(object):

    def __init__(self, header: Header = None, data: bytes = b'') -> None:
        """
        Byte bundle containing the metadata header and payload.
        """
        self._header = header if header else Header()
        self._data = data

    @property
    def header(self) -> Header:
        """
        Returns the segment header.
        """
        return self._header

    @property
    def data(self) -> bytes:
        """
        Returns the segment payload.
        """
        return self._data

    @property
    def total_size(self) -> int:
        """
        Returns the total expected size of the segment.
        """
        return len(self.header.data_length) + Header.LENGTH

    def encode(self) -> bytes:
        return self.header.encode() + self.data

    @staticmethod
    def decode(buf: bytes) -> Self:
        """
        Decodes the segment from bytes.
        """
        header = Header.decode(buf[:Header.LENGTH])
        return Segment(header, buf[Header.LENGTH:])

    def __len__(self) -> int:
        """
        Returns the total number of bytes in the segment.
        """
        return len(self.data) + Header.LENGTH

    def __repr__(self) -> str:
        """
        Returns a string representation of the segment.
        """
        return (f'<Segment channel={self.header.channel} seq={self.header.sequence} '
                f'syn={int(self.header.flags.syn)} fin={int(self.header.flags.fin)} '
                f'rst={int(self.header.flags.rst)} ack={int(self.header.flags.ack)}>')


async def nop(*args, **kwargs) -> None:
    """
    No operation coroutine.
    """
    pass


type DataReceivedCallback = Callable[[bytes], None]


class Channel(object):

    STATE_OPENING: int = 0
    STATE_OPEN: int = 1
    STATE_CLOSING: int = 2
    STATE_CLOSED: int = 3

    def __init__(self, number: int, addr: str, port: int) -> None:
        """
        Bi-directional communication channel between two endpoints.
        """
        self._number = number
        self._addr = addr
        self._port = port
        self._ready = asyncio.Event()
        self.sequence: int = 0
        self.state = self.STATE_OPENING
        self.on_data_received: DataReceivedCallback = nop

    @property
    def number(self) -> int:
        """
        Returns the channel number.
        """
        return self._number

    @property
    def address(self) -> str:
        """
        Returns the remote IP address. This is only used when opening a channel.
        """
        return self._addr

    @property
    def port(self) -> int:
        """
        Returns the remote IP port. This is only used when opening a channel.
        """
        return self._port

    @property
    def ready(self) -> asyncio.Event:
        """
        Returns the channel ready event.
        """
        return self._ready

    @property
    def is_segment(self) -> bool:
        """
        Returns whether the channel is a segment.
        """
        # datagram channels are not supported yet
        return True

    @property
    def is_datagram(self) -> bool:
        """
        Returns whether the channel is a datagram.
        """
        # datagram channels are not supported yet
        return False

    @property
    def is_open(self) -> bool:
        """
        Returns whether the channel is open.
        """
        return self.state == self.STATE_OPEN

    def next_sequence(self) -> int:
        """
        Returns the next segment sequence number.
        """
        self.sequence = self.sequence + 1 if self.sequence < 65536 else 0
        return self.sequence


class Packet(object):

    def __init__(self, channel: Channel, segment: Segment) -> None:
        """
        Transmission unit containing a channel and segment.
        """
        self._channel = channel
        self._segment = segment
        self.sent = False

    @property
    def channel(self) -> Channel:
        """
        Returns the channel associated with the packet.
        """
        return self._channel

    @property
    def segment(self) -> Segment:
        """
        Returns the segment contained in the packet.
        """
        return self._segment

    @property
    def is_ack(self) -> bool:
        """
        Returns whether the packet contains an acknowledgement segment.
        """
        return self.segment.header.flags.ack

    @property
    def is_setup(self) -> bool:
        """
        Returns whether the packet contains a channel setup segment.
        """
        header = self._segment.header
        return header.flags.syn and not (header.flags.fin or header.flags.rst)

    @property
    def is_reset(self) -> bool:
        """
        Returns whether the packet contains a channel reset segment.
        """
        header = self._segment.header
        return header.flags.rst and not (header.flags.syn or header.flags.fin)

    @property
    def is_refused(self) -> bool:
        """
        Returns whether the packet contains a channel refused segment.
        """
        header = self._segment.header
        return header.flags.syn and header.flags.rst

    @property
    def is_data(self) -> bool:
        """
        Returns whether the packet contains a data segment.
        """
        header = self._segment.header
        return not (header.flags.syn or header.flags.rst)

    @property
    def is_fin(self) -> bool:
        """
        Returns whether the packet contains a final data segment.
        """
        return self.is_data and self._segment.header.flags.fin

    def __repr__(self) -> str:
        """
        Returns a string representation of the packet.
        """
        return f'<Packet segment={self.segment} sent={int(self.sent)}>'

    def __eq__(self, other: Self) -> bool:
        """
        Compares the channel and sequence number of two packets.
        """
        if isinstance(other, Packet):
            return (self.segment.header.channel == other.segment.header.channel and
                    self.segment.header.sequence == other.segment.header.sequence)
        else:
            return False


type ChannelEventCallback = Callable[[Channel], None]


class PacketProtocol(object):

    PACKET_SIZE: int = 65535
    MAX_CHANNEL: int = 65535

    def __init__(self, packet_size: int = PACKET_SIZE) -> None:
        """
        Bi-directional communication protocol for managing channels and packets.
        """
        self._packet_size = packet_size
        self._channels: list[Channel] = {}
        self.on_remote_open: ChannelEventCallback = nop
        self.on_remote_close: ChannelEventCallback = nop

    @property
    def packet_size(self) -> int:
        """
        Returns the maximum packet size.
        """
        return self._packet_size

    def allocate_channel(self) -> int:
        """
        Allocates a new channel number.
        """
        # channel 0 is reserved for future use
        number = next((x for x in range(1, self.MAX_CHANNEL) if x not in self._channels))

        if number is None:
            raise ValueError('No available channel')

        self._channels[number] = None
        logging.debug(f'protocol: allocated channel {number}, count={len(self._channels)}')
        return number

    def free_channel(self, channel: Channel) -> None:
        """
        Deallocates a channel number.
        """
        if channel.number in self._channels:
            del self._channels[channel.number]
            logging.debug(f'protocol: deallocated channel {channel.number}, '
                          f'count={len(self._channels)}')

    async def close_channel(self, channel: Channel) -> Packet:
        """
        Closes the channel and prepares a reset packet.
        """
        segment = Segment()
        segment.header.channel = channel.number
        segment.header.sequence = channel.next_sequence()
        segment.header.flags.rst = True
        return Packet(channel, segment)

    async def open_channel(self, channel: Channel) -> Packet:
        """
        Opens a new channel and prepares a setup packet.
        """
        if channel.number not in self._channels:
            raise ValueError(f'Channel {channel.number} not found')

        segment = Segment()
        segment.header.channel = channel.number
        segment.header.address = ip_address(channel.address)
        segment.header.port = channel.port
        segment.header.sequence = channel.next_sequence()
        segment.header.flags.ip6 = segment.header.address.version == 6
        segment.header.flags.syn = True

        self._channels[channel.number] = channel
        return Packet(channel, segment)

    async def channel_setup(self, packet: Packet) -> Packet:
        """
        Acknowledges the setup packet and marks the channel as open.
        """
        header = packet.segment.header

        channel = Channel(header.channel, header.address.compressed, header.port)
        self._channels[channel.number] = channel

        logging.debug(f'protocol: ack channel {channel.number} open to '
                      f'{channel.address}:{channel.port}')

        channel.state = Channel.STATE_OPEN
        channel.sequence = header.sequence
        header.flags.ack = True

        await self.on_remote_open(channel)
        return Packet(channel, packet.segment)

    def channel_reset(self, packet: Packet) -> Packet:
        """
        Acknowledges the reset packet and marks the channel as closed.
        """
        logging.debug(f'protocol: ack channel {packet.segment.header.channel} closed')
        packet.segment.header.flags.ack = True

        if self.channel_exists(packet):
            packet.channel.state = Channel.STATE_CLOSED
            packet.channel.sequence = packet.segment.header.sequence
            packet.channel.ready.set()

            asyncio.ensure_future(self.on_remote_close(packet.channel))
            self.free_channel(packet.channel)

        return packet

    def channel_exists(self, packet: Packet) -> bool:
        """
        Checks if the channel number in the packet exists.
        """
        return packet.channel is not None and packet.channel.number in self._channels

    async def send(self, writer: Callable[[bytes], None], packet: Packet) -> None:
        """
        Sends a packet to the remote endpoint.
        """
        if packet.channel == 0:
            raise ValueError('Cannot send on channel 0')

        buf = packet.segment.encode()
        hex_header = ' '.join('{:02x}'.format(x) for x in buf[:Header.LENGTH])
        logging.debug(f'protocol: send header: {hex_header}')

        logging.debug(f'protocol: sending packet on channel {packet.segment.header.channel}')
        await writer(buf)
        packet.sent = True

    async def recv(self, reader: Callable[[int], bytes]) -> Packet:
        """
        Receives a packet from the remote endpoint.
        """
        buf = await reader()
        if len(buf) < Header.LENGTH:
            return

        segment = Segment.decode(buf)
        if len(segment.data) < segment.header.data_length:
            segment = await reader(segment.total_size)

        logging.debug(f'protocol: received {len(segment.data)} bytes '
                      f'on channel {segment.header.channel}')

        if segment.header.channel == 0:
            logging.warn('protocol: dropping segment on channel 0')
            return None

        return Packet(self._channels.get(segment.header.channel), segment)

    async def unpack(self, packet: Packet) -> None:
        """
        Unpacks the data segment and forwards it to the channel.
        """
        header = packet.segment.header
        logging.debug(f'protocol: received data segment on channel {header.channel}')

        channel = packet.channel
        channel.sequence = header.sequence
        asyncio.ensure_future(channel.on_data_received(packet.segment.data))

    def _chunk(self, data: bytes) -> tuple[list[bytes], bool]:
        """
        Splits the data into chunks of the maximum packet payload size.
        """
        chunklen = self._packet_size - Header.LENGTH

        for i in range(0, len(data), chunklen):
            yield data[i:i + chunklen], i + chunklen >= len(data)

    def pack(self, channel: Channel, data: bytes) -> Iterator[Packet]:
        """
        Packs the data into segments and prepares them for sending.
        """
        for chunk, final in self._chunk(data):
            segment = Segment(data=chunk)
            segment.header.data_length = len(chunk)
            segment.header.channel = channel.number
            segment.header.sequence = channel.next_sequence()
            segment.header.flags.fin = final
            yield Packet(channel, segment)

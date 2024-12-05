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

import logging
from ipaddress import ip_address
from typing import Self, Iterator, Callable

from .channel import Channel
from .transport import Header, Segment


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


class PacketProtocol(object):

    PACKET_SIZE: int = 65535
    MAX_CHANNEL: int = 65535

    def __init__(self, packet_size: int = PACKET_SIZE) -> None:
        """
        Bi-directional communication protocol for managing channels and packets.
        """
        self._packet_size = packet_size
        self._channels: list[Channel] = {}

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

    def close_channel(self, channel: Channel) -> Packet:
        """
        Closes the channel and prepares a reset packet.
        """
        segment = Segment()
        segment.header.channel = channel.number
        segment.header.sequence = channel.next_sequence()
        segment.header.flags.dgm = channel.is_datagram
        segment.header.flags.rst = True
        return Packet(channel, segment)

    def open_channel(self, channel: Channel, datagram: bool = False) -> Packet:
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
        segment.header.flags.dgm = datagram
        segment.header.flags.syn = True

        self._channels[channel.number] = channel
        return Packet(channel, segment)

    def channel_setup(self, packet: Packet) -> Packet:
        """
        Acknowledges the setup packet and marks the channel as open.
        """
        header = packet.segment.header

        channel = Channel(header.channel, header.address.compressed, header.port,
                          datagram=header.flags.dgm)
        self._channels[channel.number] = channel

        logging.debug(f'protocol: ack channel {channel.number} open to '
                      f'{channel.address}:{channel.port}')

        channel.state = Channel.STATE_OPENING
        channel.sequence = header.sequence
        header.sequence = channel.next_sequence()
        header.flags.ack = True

        return Packet(channel, packet.segment)

    def channel_refused(self, packet: Packet) -> Packet:
        """
        Refuses channel setup and frees the channel number.
        """
        packet.channel.state = Channel.STATE_CLOSED
        packet.segment.header.flags.rst = True
        packet.segment.header.flags.ack = False

        self.free_channel(packet.channel)
        return packet

    def channel_reset(self, packet: Packet) -> Packet:
        """
        Acknowledges the reset packet and marks the channel as closed.
        """
        logging.debug(f'protocol: ack channel {packet.segment.header.channel} closed')
        packet.segment.header.flags.ack = True

        if self.channel_exists(packet):
            packet.channel.state = Channel.STATE_CLOSED
            packet.channel.sequence = packet.segment.header.sequence
            packet.segment.header.sequence = packet.channel.next_sequence()
            packet.channel.ready.set()

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

        channel = self._channels.get(segment.header.channel)

        if channel and segment.header.flags.ack:
            logging.debug(f'protocol: received ack {segment}')
            channel.sequence = segment.header.sequence
            channel.ready.set()
            return None
        elif not channel and not segment.header.flags.syn:
            logging.warn('protocol: dropping segment on unknown channel')
            return None

        return Packet(channel, segment)

    def unpack(self, packet: Packet) -> bytes:
        """
        Unpacks the data segment and forwards it to the channel.
        """
        header = packet.segment.header
        logging.debug(f'protocol: received data segment on channel {header.channel}')

        channel = packet.channel
        channel.sequence = header.sequence
        return packet.segment.data

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
            segment.header.flags.dgm = channel.is_datagram
            segment.header.flags.fin = final
            yield Packet(channel, segment)

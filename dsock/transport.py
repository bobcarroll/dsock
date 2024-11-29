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

from ipaddress import IPv4Address, IPv6Address
from typing import Self


class Flags(object):

    def __init__(self) -> None:
        """
        Bitfield for transmission options.
        """
        # segment contains an acknowledgement
        self.ack: bool = False
        # segment is a datagram
        self.dgm: bool = False
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
        buf |= self.dgm << 5
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
        self.dgm = bool(flags & 0b00100000)
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
                f'rst={int(self.header.flags.rst)} ack={int(self.header.flags.ack)} '
                f'dgm={int(self.header.flags.dgm)}>')

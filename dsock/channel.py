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
from typing import Callable

type ChannelEventCallback = Callable[[Channel], None]
type DataReceivedCallback = Callable[[bytes], None]


async def nop(*args, **kwargs) -> None:
    """
    No operation coroutine.
    """
    pass


class Channel(object):

    STATE_OPENING: int = 0
    STATE_OPEN: int = 1
    STATE_CLOSING: int = 2
    STATE_CLOSED: int = 3

    def __init__(self, number: int, addr: str, port: int, datagram: bool = False) -> None:
        """
        Bi-directional communication channel between two endpoints.
        """
        self._number = number
        self._addr = addr
        self._port = port
        self._ready = asyncio.Event()
        self._datagram = datagram
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
    def is_datagram(self) -> bool:
        """
        Returns whether the channel handles datagram packets.
        """
        return self._datagram

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

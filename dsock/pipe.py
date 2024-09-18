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

import os
import io
import asyncio
import logging
from typing import Self, Callable
from contextlib import contextmanager

type BufferHandle = tuple[io.FileIO, str]


class Frame(object):

    HEADER_SIZE: int = 4

    def __init__(self, data: bytes = b'') -> None:
        """
        A byte blob with metadata.
        """
        self._data = data
        self._size = len(data)

    @property
    def data(self) -> bytes:
        """
        Returns the payload bytes.
        """
        return self._data

    def __len__(self) -> int:
        """
        Returns the payload byte count.
        """
        return self._size

    def encode(self) -> bytes:
        """
        Converts the frame to a byte array.
        """
        return self._size.to_bytes(self.HEADER_SIZE) + self._data

    @staticmethod
    def decode(reader: Callable[[int], bytes]) -> Self:
        """
        Converts a byte array to a frame.
        """
        size = int.from_bytes(reader(Frame.HEADER_SIZE))
        return Frame(reader(size))


class Pipe(object):

    BUFFER_SIZE: int = 4194304  # 4MB
    PAGE_SIZE: int = BUFFER_SIZE + Frame.HEADER_SIZE
    FILE_SIZE: int = PAGE_SIZE + 1

    POLL_FREQ: float = 0.001

    WCB_NULL: bytes = b'\x00'
    WCB_DATA: bytes = b'\x01'

    def __init__(self, path: str, server: bool = False, reuse_handles: bool = True) -> None:
        """
        A file-based pipe for remote communication.
        """
        self.reader: BufferHandle = self.allocate(path + '.1' if server else path + '.2')
        self.writer: BufferHandle = self.allocate(path + '.2' if server else path + '.1')
        self._reuse_handles = reuse_handles

    def allocate(self, path: str) -> BufferHandle:
        """
        Allocates the pipe's buffer files.
        """
        def _allocate(path: str):
            with open(path, 'wb') as f:
                f.write(b'\x00' * self.FILE_SIZE)
            logging.info(f'pipe: allocated {self.FILE_SIZE} bytes to {path}')

        if not os.path.exists(path):
            _allocate(path)

        return (open(path, 'r+b', buffering=0), path)

    @contextmanager
    def open_reader(self) -> io.FileIO:
        """
        Opens a handle to the read buffer.
        """
        f, path = self.reader

        if self._reuse_handles:
            f.seek(0)
            yield f
        else:
            f.close()
            self.reader = self.allocate(path)
            yield self.reader[0]

    @contextmanager
    def open_writer(self) -> io.FileIO:
        """
        Opens a handle to the write buffer.
        """
        f, path = self.writer

        if self._reuse_handles:
            f.seek(0)
            yield f
        else:
            f.close()
            self.writer = self.allocate(path)
            yield self.writer[0]
            self.writer[0].flush()

    async def read(self, min_size: int = 0) -> bytes:
        """
        Read data from the pipe.
        """
        if min_size > self.BUFFER_SIZE:
            raise ValueError('Minimum size exceeds buffer size')

        while True:
            with self.open_reader() as f:
                wcb = f.read(1)
                if wcb == self.WCB_NULL:
                    return b''

                frame = Frame.decode(f.read)
                if len(frame) < min_size:
                    await asyncio.sleep(self.POLL_FREQ)
                    continue

            if len(frame) > 0:
                logging.debug(f'pipe: read {len(frame)} bytes from {self.reader[1]}')

            await self._truncate()
            return frame.data

    async def _truncate(self) -> None:
        """
        Sets the write control byte to NULL, effectively emptying the buffer.
        """
        with self.open_reader() as f:
            f.write(b'\x00' * 5)

    async def _wait_write(self) -> None:
        """
        Waits for the write control byte to be set to NULL. This indicates that the
        receiving process has read the data from the buffer.
        """
        while True:
            await asyncio.sleep(self.POLL_FREQ)

            with self.open_writer() as f:
                wcb = f.read(1)
                if wcb == self.WCB_NULL:
                    return

    async def write(self, data: bytes) -> None:
        """
        Writes data to the pipe.
        """
        if len(data) > self.BUFFER_SIZE:
            raise ValueError('Data length exceeds buffer size')

        await self._wait_write()

        with self.open_writer() as f:
            f.write(self.WCB_NULL + Frame(data).encode())
            f.flush()
            f.seek(0)
            f.write(self.WCB_DATA)

        logging.debug(f'pipe: wrote {len(data)} bytes to {self.writer[1]}')

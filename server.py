
import sys
import asyncio
import logging

import dsock

config = {
    'win': {
        # server side of the pipe socket
        'pipes': ['C:\\Users\\bob\\web.sock'],
        # client side of the pipe socket
        # local address, local port, remote address, remote port, pipe path
        'sockets': [
            ('127.0.0.1', 1433, '127.0.0.1', 1433, 'C:\\Users\\bob\\mssql.sock')]},
    'vm': {
        'pipes': ['/mnt/win/home/mssql.sock'],
        'sockets': [
            ('127.0.0.1', 9000, '127.0.0.1', 80, '/mnt/win/home/web.sock')]}}


async def main(key: str) -> None:
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.DEBUG)
    tasks = []

    # for when direct I/O isn't available on the file share
    # dsock.reuse_handles = False

    for pipe in config.get(key, {}).get('pipes', []):
        tasks.append(asyncio.create_task(dsock.start_pipe_server(pipe)))

    for item in config.get(key, {}).get('sockets', []):
        tasks.append(asyncio.create_task(dsock.start_listener(*item)))

    await asyncio.gather(*tasks)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f'USAGE: {sys.argv[0]} <config key>')
        sys.exit(1)

    asyncio.run(main(sys.argv[1]))

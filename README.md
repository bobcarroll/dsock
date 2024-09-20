# dsock

dsock is a bi-directional, multiplexing socket server that acts as a proxy between two machines
sharing a common file system. This is useful in situations where there is no direct network
connectivity. For example, dsock would enable connectivity to a service over a Windows remote
desktop session.

## Quick Start

There are no dependencies other than Python 3.12. Clone the repository and update the configuration
dictionary in `server.py`. The library package can be installed in site-packages although it isn't
necessary for running the server.

As an example scenario, connecting to machine A's port 8080 will reach machine B's port 80:

```python
config = {
    'a': {'pipes': [], 'sockets': [('127.0.0.1', 8080, '127.0.0.1', 80, '/mnt/share/web.sock')]},
    'b': {'pipes': ['/mnt/share/web.sock'], 'sockets': []}}
```

Then start the server on A:

```
$ python server.py a
```

And also on B:

```
$ python server.py b
```

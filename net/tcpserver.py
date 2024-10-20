import socket
import threading
from datetime import datetime
from time import time, perf_counter
from queue import Queue, Empty

from .common import EventManager, Packet, Header, PacketFormat, ConnectionProfile, build_packet


class TCPServer:
    """
    Base class for hosting a TCP server.

    This class provides functionality to start a TCP server, listen to incoming
    connections and manage communication between clients.
    The listening is non-blocking.

    Parameters
    ----------
    host
        Hostname or IPv4 address to bind the server to.
    port
        The port number to listen on.
    backlog
        Number of unaccepted connections allowed to queue.
    max_connections
        Maximum number of connections the server allows at a time.
        0 means no limit defined.

    Events
    ------
    on_ready(client)
        Triggered when the server is all ready to listen for connections.
    on_connect(client)
        Triggered when a new client connection is established.
    on_disconnect(client)
        Triggered when a client is disconnected.
    on_packet(packet, client)
        Triggered when a packet is received.
    """

    def __init__(self,
            host: str,
            port: int,
            backlog: int = 5,
            max_connections: int = 0
            ) -> None:
        super().__init__()

        self._host = host
        self._port = port
        self._backlog = backlog
        self._max_connections = max_connections
        self._conn_sem = threading.Semaphore(self._max_connections)
        
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind((self._host, self._port))

        self.clients: list[TCPClientConnection] = list()
        self._packet_counter = 0

        self._event_manager = EventManager()
        self.register = self._event_manager.register

        self._is_running = False

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self._host}:{self._port}, {len(self.clients)} connections)>"

    def start(self) -> None:
        """ Start the server. """

        self._is_running = True

        self.listener_thread = threading.Thread(target=self._listen_job, daemon=False)
        self.listener_thread.start()

    def stop(self) -> None:
        """ Stop the server and release the resources. """

        self._is_running = False
        self._socket.close()
        self._conn_sem.release()

        self.listener_thread.join()

        for client in self.clients:
            client.disconnect()
        
        for client in self.clients:
            client._listener_thread.join()
            client._processer_thread.join()
            client._sender_thread.join()

    def _listen_job(self) -> None:
        """ Connection listener thread. """

        self._socket.listen(self._backlog)
        self._event_manager.trigger("on_ready")

        while self._is_running:
            # Block if max connections is reached
            if self._max_connections > 0:
                self._conn_sem.acquire()

            try:
                connection, address_pair = self._socket.accept()

            except OSError as e:
                # Server might've been stopped while listening
                if not self._is_running: break
                else: raise e

            client = TCPClientConnection(
                self,
                connection,
                address_pair[0],
                address_pair[1],
                len(self.clients)
            )

            self.clients.append(client)
            self._event_manager.trigger("on_connect", client)
            client._start()
    
    @property
    def host(self) -> str:
        """ Hostname or IPv4 address. """
        return self._host
    
    @property
    def port(self) -> int:
        """ The port number. """
        return self._port


class TCPClientConnection:
    """
    Client connection to the TCP server.

    This class shouldn't be created manually, the server manages connections.

    Attributes
    ----------
    id
        Unique identifier of this connection.
        Two clients' IDs can be same at different times if both are not
        existant in the server at the same time.
    connected_at
        Timestamp of the start of the connection
    """

    def __init__(self,
            server: TCPServer,
            socket_: socket.socket,
            host: str,
            port: int,
            id_: int
            ) -> None:
        self.id = id_
        self.connected_at = datetime.fromtimestamp(time())

        self._server = server
        self._socket = socket_
        self._host = host
        self._port = port

        self._outgoing = Queue()
        self._incoming = Queue()
        self._queue_timeout = 0.1

        self._is_running = False

        self._listener_thread: threading.Thread
        self._processer_thread: threading.Thread
        self._sender_thread: threading.Thread
        self._listener_time = 0.0
        self._processer_time = 0.0
        self._sender_time = 0.0

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self.id}, {self._host}:{self._port})>"

    def _start(self) -> None:
        self._is_running = True

        self._listener_thread = threading.Thread(target=self._listen_job, daemon=False)
        self._listener_thread.start()

        self._processer_thread = threading.Thread(target=self._process_job, daemon=False)
        self._processer_thread.start()

        self._sender_thread = threading.Thread(target=self._send_job, daemon=False)
        self._sender_thread.start()

    def disconnect(self) -> None:
        """ Disconnect client from server. """

        # Two threads might call this at the same time
        if (not self._is_running): return
        self._is_running = False
  
        self._server.clients.remove(self)
        self._server._event_manager.trigger("on_disconnect", self)
        self._socket.close()
        self._server._conn_sem.release()

    def _listen_job(self) -> None:
        """
        Listener thread.
        
        Receive header (6 bytes) -> Receive rest of the packet -> Put into queue.
        """

        while self._is_running:
            frame_start = perf_counter()

            try:
                # Receive header
                in_packet_data = self._socket.recv(6)
            
            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                return

            except OSError as e:
                if not self._is_running:
                    self.disconnect()
                    return

                else: raise e

            if not in_packet_data:
                self.disconnect()
                return

            header = Header(PacketFormat(int(in_packet_data[0])), int(in_packet_data[1:]))

            # Receive rest of the package
            try:
                in_packet_data = self._socket.recv(header.length)
                recv_time = perf_counter()

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                return

            except OSError as e:
                if not self._is_running:
                    self.disconnect()
                    return

                else: raise e

            # Connection closed while receiving, do not issue any more packets
            if not self._is_running:
                return

            in_packet = Packet(in_packet_data, header, recv_time)
            self._incoming.put(in_packet)
            self._server._packet_counter += 1

            self.listener_time = perf_counter() - frame_start

    def _process_job(self) -> None:
        """ Packet processer thread. """

        while self._is_running:
            frame_start = perf_counter()
            
            try:
                packet = self._incoming.get(timeout=self._queue_timeout)
            except Empty:
                continue

            if packet.header.format == PacketFormat.HEARTBEAT_PING:
                out_packet = build_packet(PacketFormat.HEARTBEAT_PONG.value, b"")

                try:
                    self._socket.sendall(out_packet)

                except (ConnectionResetError, ConnectionAbortedError):
                    self.disconnect()
                    break

            else:
                self._server._event_manager.trigger("on_packet", packet, self)

            self._incoming.task_done()

            self.processer_time = perf_counter() - frame_start

    def _send_job(self) -> None:
        """ Packet sender thread. """

        while self._is_running:
            frame_start = perf_counter()

            try:
                data = self._outgoing.get(timeout=self._queue_timeout)
            except Empty:
                continue

            packet = build_packet(PacketFormat.RAW.value, data)

            try:
                self._socket.sendall(packet)

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            self.sender_time = perf_counter() - frame_start

    @property
    def connection_profile(self) -> ConnectionProfile:
        """ Connection timings. """
        return ConnectionProfile(
            self._listener_time,
            self._processer_time,
            self._sender_time
        )
    
    @property
    def host(self) -> str:
        """ Hostname or IPv4 address. """
        return self._host
    
    @property
    def port(self) -> int:
        """ The port number. """
        return self._port
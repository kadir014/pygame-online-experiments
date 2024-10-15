from typing import Callable

import socket
import struct
import threading
from datetime import datetime
from time import time, perf_counter, sleep
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty


HOSTNAME = socket.gethostname()
LOCALHOST = socket.gethostbyname(HOSTNAME)


def build_header(fmt: int, length: int) -> bytes:
    """
    Build packet header from given format and length.

    Parameters
    ----------
    @param fmt Format of the packet, in range [0-9]
    @param length Length of the rest of the packet

    Return
    ------
    @return bytes Header consisting of 5 bytes
    """

    return struct.pack("H", fmt)[:1] + str(length).zfill(5).encode()

def build_packet(fmt: int, data: bytes) -> bytes:
    """
    Build packet from given format and data.

    Parameters
    ----------
    @param fmt Format of the packet, in range [0-9]
    @param data Raw binary data

    Return
    ------
    @return bytes Packet consisting of header + data
    """

    return build_header(fmt, len(data)) + data


class PacketFormat(Enum):
    HEARTBEAT_PING = 0
    HEARTBEAT_PONG = 1
    RAW = 2


@dataclass
class Header:
    """
    Packet header.
    """

    format: PacketFormat
    length: int


@dataclass
class Packet:
    """
    Raw binary packet.
    """

    data: bytes
    header: Header
    timestamp: float


class EventManager:
    """
    Event manager is for registering, triggering, and handling events
    with custom callbacks.
    """

    def __init__(self) -> None:
        self.__event_callbacks = {}

    def register(self, event_callback: Callable) -> None:
        """ Register a callback as an event. """

        event_name = event_callback.__name__

        if event_name not in self.__event_callbacks:
            self.__event_callbacks[event_name] = []

        self.__event_callbacks[event_name].append(event_callback)

    def trigger(self, event_name: str, *args, **kwargs) -> None:
        """ Trigger an event. """

        if event_name not in self.__event_callbacks: return

        for event_callback in self.__event_callbacks[event_name]:
            event_callback(*args, **kwargs)


class TCPServer(threading.Thread):
    """
    Base class for hosting a TCP server.
    """

    def __init__(self, address: str, port: int, backlog: int = 5) -> None:
        super().__init__()

        self.address = address
        self.port = port
        self.backlog = backlog
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.address, self.port))

        self.clients: list[TCPClientConnection] = list()
        self._packet_counter = 0

        self.event_manager = EventManager()

        self.is_running = False

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self.address}:{self.port}, {len(self.clients)} connections)>"

    def start(self) -> None:
        """ Start the server. """

        self.is_running = True
        super().start()

    def stop(self) -> None:
        """ Stop the server and release the connection threads. """

        self.is_running = False
        self.socket.close()

        for client in self.clients:
            client.stop()
            client.join()

    def run(self) -> None:
        self.socket.listen(self.backlog)
        self.event_manager.trigger("on_ready")

        while self.is_running:
            try:
                connection, address_pair = self.socket.accept()

            except OSError as e:
                # Server might've been stopped while listening
                if not self.is_running: break
                else: raise e

            client = TCPClientConnection(
                self,
                connection,
                address_pair[0],
                address_pair[1],
                len(self.clients)
            )

            self.clients.append(client)
            self.event_manager.trigger("on_connect", client)
            client._start()


class TCPClientConnection:
    """
    Client connection to the TCP server.

    This class shouldn't be created manually, the server manages connections.
    """

    def __init__(self,
            server: TCPServer,
            socket_: socket.socket,
            address: str,
            port: int,
            id_: int
            ) -> None:
        super().__init__()

        self.server = server
        self.socket = socket_
        self.address = address
        self.port = port
        self.id = id_
        self.connected_at = datetime.fromtimestamp(time())

        self.outgoing = Queue()
        self.incoming = Queue()
        self.queue_timeout = 0.1

        self.is_running = False

        self.listener_thread: threading.Thread
        self.processer_thread: threading.Thread
        self.sender_thread: threading.Thread
        self.listener_time = 0.0
        self.processer_time = 0.0
        self.sender_time = 0.0

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self.id}, {self.address}:{self.port})>"

    def _start(self) -> None:
        self.is_running = True

        self.listener_thread = threading.Thread(target=self._listen_job, daemon=False)
        self.listener_thread.start()

        self.processer_thread = threading.Thread(target=self._process_job, daemon=False)
        self.processer_thread.start()

        self.sender_thread = threading.Thread(target=self._send_job, daemon=False)
        self.sender_thread.start()

    def disconnect(self) -> None:
        """ Disconnect client from server. """

        # Two threads might call this at the same time
        if (not self.is_running): return
        self.is_running = False
  
        self.server.clients.remove(self)
        self.server.event_manager.trigger("on_disconnect", self)
        self.socket.close()

    def send_raw(self, data: bytes) -> None:
        """ Send raw packet to the server. """

        packet = build_packet(PacketFormat.RAW.value, data)
        self.socket.sendall(packet)

    def _listen_job(self) -> None:
        """
        Listener thread.
        
        Receive header (6 bytes) -> Receive rest of the packet -> Put into queue.
        """

        while self.is_running:
            frame_start = perf_counter()

            try:
                # Receive header
                in_packet_data = self.socket.recv(6)
            
            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                return

            except OSError as e:
                if not self.is_running:
                    self.disconnect()
                    return

                else: raise e

            if not in_packet_data:
                self.disconnect()
                return

            header = Header(PacketFormat(int(in_packet_data[0])), int(in_packet_data[1:]))

            # Receive rest of the package
            try:
                in_packet_data = self.socket.recv(header.length)
                recv_time = perf_counter()

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                return

            except OSError as e:
                if not self.is_running:
                    self.disconnect()
                    return

                else: raise e

            # Connection closed while receiving, do not issue any more packets
            if not self.is_running:
                return

            in_packet = Packet(in_packet_data, header, recv_time)
            self.incoming.put(in_packet)
            self.server._packet_counter += 1

            self.listener_time = perf_counter() - frame_start

    def _process_job(self) -> None:
        """ Packet processer thread. """

        while self.is_running:
            frame_start = perf_counter()
            
            try:
                packet = self.incoming.get(timeout=self.queue_timeout)
            except Empty:
                continue

            if packet.header.format == PacketFormat.HEARTBEAT_PING:
                out_packet = build_packet(PacketFormat.HEARTBEAT_PONG.value, b"")

                try:
                    self.socket.sendall(out_packet)

                except (ConnectionResetError, ConnectionAbortedError):
                    self.disconnect()
                    break

            else:
                self.server.event_manager.trigger("on_packet", packet, self)

            self.incoming.task_done()

            self.processer_time = perf_counter() - frame_start

    def _send_job(self) -> None:
        """ Packet sender thread. """

        while self.is_running:
            frame_start = perf_counter()

            try:
                data = self.outgoing.get(timeout=self.queue_timeout)
            except Empty:
                continue

            packet = build_packet(PacketFormat.RAW.value, data)

            try:
                self.socket.sendall(packet)

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            self.sender_time = perf_counter() - frame_start


class TCPClient:
    """
    Base class for hosting a TCP client and connecting to an existing server.
    """

    def __init__(self,
            address: str,
            port: int
            ) -> None:
        super().__init__()

        self.address = address
        self.port = port

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.latency = 0.0
        self._heartbeat_last = 0.0
        self._heartbeat_sent = 0.0
        self._is_heartbeat_done = True

        self.event_manager = EventManager()

        self.outgoing = Queue()
        self.incoming = Queue()
        self.queue_timeout = 0.1

        self.is_running = False

        self.listener_thread: threading.Thread
        self.processer_thread: threading.Thread
        self.sender_thread: threading.Thread
        self.listener_time = 0.0
        self.processer_time = 0.0
        self.sender_time = 0.0

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self.address}:{self.port})>"

    def start(self) -> None:
        """ Start the connection. """

        self.is_running = True

        self.socket.connect((self.address, self.port))
        self.event_manager.trigger("on_connect")
        
        self.listener_thread = threading.Thread(target=self._listen_job, daemon=False)
        self.listener_thread.start()

        self.processer_thread = threading.Thread(target=self._process_job, daemon=False)
        self.processer_thread.start()

        self.sender_thread = threading.Thread(target=self._send_job, daemon=False)
        self.sender_thread.start()

    def disconnect(self) -> None:
        """ Stop the connection. """

        # Two threads might call this at the same time
        if not self.is_running: return
        self.is_running = False

        self.event_manager.trigger("on_disconnect")
        self.socket.close()

    def send_raw(self, data: bytes) -> None:
        """ Send raw packet to the server. """

        packet = build_packet(PacketFormat.RAW.value, data)
        self.socket.sendall(packet)

    def _listen_job(self) -> None:
        """
        Listener thread.
        
        Receive header (6 bytes) -> Receive rest of the packet -> Put into queue
        """

        while self.is_running:
            frame_start = perf_counter()

            try:
                # Receive header
                in_packet_data = self.socket.recv(6)
            
            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            except OSError as e:
                if not self.is_running:
                    self.disconnect()
                    break

                else: raise e
                
            if not in_packet_data:
                self.disconnect()
                break

            header = Header(PacketFormat(int(in_packet_data[0])), int(in_packet_data[1:]))

            # Receive rest of the packet
            try:
                in_packet_data = self.socket.recv(header.length)
                recv_time = perf_counter()

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            except OSError as e:
                if not self.is_running:
                    self.disconnect()
                    break

                else: raise e

            # Connection closed while receiving, do not issue any more packets
            if not self.is_running:
                break

            in_packet = Packet(in_packet_data, header, recv_time)
            self.incoming.put(in_packet)

            self.listener_time = perf_counter() - frame_start

    def _process_job(self) -> None:
        """ Packet processer thread. """

        while self.is_running:
            frame_start = perf_counter()

            try:
                packet = self.incoming.get(timeout=self.queue_timeout)
            except Empty:
                continue

            if packet.header.format == PacketFormat.HEARTBEAT_PONG:
                self._is_heartbeat_done = True
                self.latency = packet.timestamp - self._heartbeat_sent

            else:
                self.event_manager.trigger("on_packet", packet)

            self.incoming.task_done()

            self.processer_time = perf_counter() - frame_start

    def _send_job(self) -> None:
        """ Packet sender thread. """

        while self.is_running:
            frame_start = perf_counter()

            # Send heartbeat ping
            if self._is_heartbeat_done and time() - self._heartbeat_last >= 0.5:
                self._heartbeat_last = time()
                self._is_heartbeat_done = False
                self._heartbeat_sent = perf_counter()

                try:
                    hb_packet = build_packet(PacketFormat.HEARTBEAT_PING.value, b"")
                    self.socket.sendall(hb_packet)

                except (ConnectionResetError, ConnectionAbortedError):
                    self.disconnect()
                    break

            try:
                data = self.outgoing.get(timeout=self.queue_timeout)
            except Empty:
                continue

            packet = build_packet(PacketFormat.RAW.value, data)

            try:
                self.socket.sendall(packet)

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            self.sender_time = perf_counter() - frame_start
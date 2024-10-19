import socket
import threading
from time import time, perf_counter
from queue import Queue, Empty

from .common import EventManager, Packet, Header, PacketFormat, build_packet, ConnectionProfile


class TCPClient:
    """
    Base class for hosting a TCP client and connecting to an existing server.

    This class facilitates a TCP connections, sending messages, and receiving 
    responses from the server. It provides methods for managing the connection state.

    Parameters
    ----------
    host
        Hostname or IPv4 address of the server to connect to.
    port
        The port number to connect on.

    Events
    ------
    on_connect()
        Triggered when the connection is established.
    on_disconnect()
        Triggered when disconnected.
    on_packet(packet)
        Triggered when a packet is received.
    """

    def __init__(self,
            host: str,
            port: int
            ) -> None:
        super().__init__()

        self._host = host
        self._port = port

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.latency = 0.0
        self._heartbeat_last = 0.0
        self._heartbeat_sent = 0.0
        self._is_heartbeat_done = True

        self._event_manager = EventManager()
        self.register = self._event_manager.register

        self.outgoing = Queue()
        self.incoming = Queue()
        self.queue_timeout = 0.1

        self._is_running = False

        self._listener_thread: threading.Thread
        self._processer_thread: threading.Thread
        self._sender_thread: threading.Thread
        self._listener_time = 0.0
        self._processer_time = 0.0
        self._sender_time = 0.0

    def __repr__(self) -> str:
        return f"<{__name__}.{self.__class__.__name__}({self._host}:{self._port})>"

    def connect(self) -> None:
        """ Start the connection. """

        self._is_running = True

        self._socket.connect((self._host, self._port))
        self._event_manager.trigger("on_connect")
        
        self._listener_thread = threading.Thread(target=self._listen_job, daemon=False)
        self._listener_thread.start()

        self._processer_thread = threading.Thread(target=self._process_job, daemon=False)
        self._processer_thread.start()

        self._sender_thread = threading.Thread(target=self._send_job, daemon=False)
        self._sender_thread.start()

    def disconnect(self) -> None:
        """ Stop the connection. """

        # Two threads might call this at the same time
        if not self._is_running: return
        self._is_running = False

        self._event_manager.trigger("on_disconnect")
        self._socket.close()

    def _listen_job(self) -> None:
        """
        Listener thread.
        
        Receive header (6 bytes) -> Receive rest of the packet -> Put into queue
        """

        while self._is_running:
            frame_start = perf_counter()

            try:
                # Receive header
                in_packet_data = self._socket.recv(6)
            
            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            except OSError as e:
                if not self._is_running:
                    self.disconnect()
                    break

                else: raise e
                
            if not in_packet_data:
                self.disconnect()
                break

            header = Header(PacketFormat(int(in_packet_data[0])), int(in_packet_data[1:]))

            # Receive rest of the packet
            try:
                in_packet_data = self._socket.recv(header.length)
                recv_time = perf_counter()

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            except OSError as e:
                if not self._is_running:
                    self.disconnect()
                    break

                else: raise e

            # Connection closed while receiving, do not issue any more packets
            if not self._is_running:
                break

            in_packet = Packet(in_packet_data, header, recv_time)
            self.incoming.put(in_packet)

            self._listener_time = perf_counter() - frame_start

    def _process_job(self) -> None:
        """ Packet processer thread. """

        while self._is_running:
            frame_start = perf_counter()

            try:
                packet = self.incoming.get(timeout=self.queue_timeout)
            except Empty:
                continue

            if packet.header.format == PacketFormat.HEARTBEAT_PONG:
                self._is_heartbeat_done = True
                self.latency = packet.timestamp - self._heartbeat_sent

            else:
                self._event_manager.trigger("on_packet", packet)

            self.incoming.task_done()

            self._processer_time = perf_counter() - frame_start

    def _send_job(self) -> None:
        """ Packet sender thread. """

        while self._is_running:
            frame_start = perf_counter()

            # Send heartbeat ping
            if self._is_heartbeat_done and time() - self._heartbeat_last >= 0.5:
                self._heartbeat_last = time()
                self._is_heartbeat_done = False
                self._heartbeat_sent = perf_counter()

                try:
                    hb_packet = build_packet(PacketFormat.HEARTBEAT_PING.value, b"")
                    self._socket.sendall(hb_packet)

                except (ConnectionResetError, ConnectionAbortedError):
                    self.disconnect()
                    break

            try:
                data = self.outgoing.get(timeout=self.queue_timeout)
            except Empty:
                continue

            packet = build_packet(PacketFormat.RAW.value, data)

            try:
                self._socket.sendall(packet)

            except (ConnectionResetError, ConnectionAbortedError):
                self.disconnect()
                break

            self._sender_time = perf_counter() - frame_start

    @property
    def connection_profile(self) -> ConnectionProfile:
        return ConnectionProfile(
            self._listener_time,
            self._processer_time,
            self._sender_time
        )
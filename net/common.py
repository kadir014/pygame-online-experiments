from typing import Callable

import socket
import struct
from dataclasses import dataclass
from enum import Enum


HOSTNAME = socket.gethostname()
LOCALHOST = socket.gethostbyname(HOSTNAME)


def build_header(fmt: int, length: int) -> bytes:
    """
    Build packet header from given format and length.

    Parameters
    ----------
    fmt
        Format of the packet, in range [0-9].
    length
        Length of the rest of the packet.

    Returns
    -------
    bytes
        Header data consisting of 5 bytes.
    """

    return struct.pack("H", fmt)[:1] + str(length).zfill(5).encode()

def build_packet(fmt: int, data: bytes) -> bytes:
    """
    Build packet from given format and data.

    Parameters
    ----------
    fmt
        Format of the packet, in range [0-9].
    data
        Raw binary data.

    Returns
    -------
    bytes
        Packet consisting of header + data.
    """

    return build_header(fmt, len(data)) + data


class PacketFormat(Enum):
    """
    Reserved packet formats.
    """

    RAW = 0
    HEARTBEAT_PING = 1
    HEARTBEAT_PONG = 2


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


@dataclass
class ConnectionProfile:
    """
    Timings of a connection frame.
    """

    listener_time: float
    processer_time: float
    sender_time: float


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
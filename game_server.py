import time
import json
from dataclasses import dataclass

import keyboard
import pygame

import net
from terminal import FG, RESET


@dataclass
class Player:
    position: pygame.Vector2
    name: str
    color: tuple[int, int, int]

    def serialize(self) -> str:
        return json.dumps({"name": self.name, "color": self.color})


clock = pygame.time.Clock()

server = net.TCPServer("127.0.0.1", 65432)

stopped = False
def stop():
    global stopped
    stopped = True
    try:
        server.stop()
    except Exception as e:
        print("Exception occured while shutting down server:")
        raise e

keyboard.add_hotkey("esc", stop)

players: dict[net.TCPClientConnection, Player] = {}

@server.register
def on_ready():
    print(f"{FG.lightcyan}Server started to listen for connections at {RESET}{server.host}{FG.darkgray}:{RESET}{server.port}")

@server.register
def on_connect(client: net.TCPClientConnection):
    print(f"{FG.lightgreen}New connection from {RESET}{client.host}{FG.darkgray}:{RESET}{client.port} {FG.lightgreen}is given ID {RESET}{client.id}")
    players[client] = Player(pygame.Vector2(), "unknown", (0, 0, 0))

@server.register
def on_disconnect(client: net.TCPClientConnection):
    print(f"{FG.orange}Client#{RESET}{client.id} {FG.orange}disconnected.{RESET}")

@server.register
def on_packet(packet: net.common.Packet, client: net.TCPClientConnection):
    data = packet.data.decode()

    # Player name
    if data.startswith("_"):
        deserialized = json.loads(data[1:])
        players[client].name = deserialized["name"]
        players[client].color = deserialized["color"]
        print(f"Client data received: {players[client].name}")

        if len(server.clients) > 1:
            for client2 in server.clients:
                if client is client2: continue

                outdata = json.dumps({"id": client.id, "name": players[client].name, "color": players[client].color})
                client2._outgoing.put(f"_{outdata}".encode())

                outdata = json.dumps({"id": client2.id, "name": players[client2].name, "color": players[client2].color})
                client._outgoing.put(f"_{outdata}".encode())

    # Coordinates
    else:
        posdata = data.split(",")
        x, y = float(posdata[0]), float(posdata[1])
        players[client].position = pygame.Vector2(x, y)

server.start()

start = time.time()
while not stopped:
    clock.tick(60)

    if len(server.clients) > 1:
        for client in server.clients:
            s = {}
            for client2 in players:
                if client is client2: continue
                player = players[client2]

                s[client2.id] = (player.position.x, player.position.y)

            if s:
                data = json.dumps(s).encode()
                client._outgoing.put(data)

    # Remove disconnected clients
    new_players = {}
    for client in players:
        if client not in server.clients: continue
        new_players[client] = players[client]
    players = new_players.copy()

    if time.time() - start >= 5.0:
        start = time.time()
        print(f"{server._packet_counter} packets received ({round(server._packet_counter / 5.0, 2)} packets/s)")
        server._packet_counter = 0
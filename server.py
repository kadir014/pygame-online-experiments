import time

import keyboard
import pygame

import net
from terminal import FG, RESET


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

player_positions = {}

@server.event_manager.register
def on_ready():
    print(f"{FG.lightcyan}Server started to listen for connections at {RESET}{server.address}{FG.darkgray}:{RESET}{server.port}")

@server.event_manager.register
def on_connect(client: net.TCPClientConnection):
    print(f"{FG.lightgreen}New connection from {RESET}{client.address}{FG.darkgray}:{RESET}{client.port} {FG.lightgreen}is given ID {RESET}{client.id}")

@server.event_manager.register
def on_disconnect(client: net.TCPClientConnection):
    print(f"{FG.orange}Client#{RESET}{client.id} {FG.orange}disconnected.{RESET}")

@server.event_manager.register
def on_packet(packet: net.Packet, client: net.TCPClientConnection):
    #print(packet.data)
    data = packet.data.decode().split(",")
    x, y = int(data[0]), int(data[1])
    player_positions[client] = (x, y)
    #print("new player packet")

server.start()

start = time.time()
while not stopped:
    clock.tick(120)

    if len(server.clients) > 1:
        for client in server.clients:
            s = ""
            for client2 in player_positions:
                if client is client2: continue
                pos = player_positions[client2]

                s += f"{pos[0]},{pos[1]};"

            s = s[:-1] # Don't include the last ';'

            data = s.encode()

            if data:
                #client.send_raw(data)
                client.outgoing.put(data)

    # Remove disconnected clients
    new_positions = {}
    for client in player_positions:
        if client not in server.clients: continue
        new_positions[client] = player_positions[client]
    player_positions = new_positions.copy()

    if time.time() - start >= 5.0:
        start = time.time()
        print(f"{server._packet_counter} packets received ({round(server._packet_counter / 5.0, 2)} packets/s)")
        server._packet_counter = 0

    #if len(server.clients) > 0:
    #    print(f"processer: {round((server.clients[0].processer_time) * 1000.0, 2)}ms listener: {round((server.clients[0].listener_time) * 1000.0, 2)}ms")
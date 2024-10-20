import net
from terminal import FG, RESET


server = net.TCPServer(net.common.LOCALHOST, 65432)

@server.register
def on_ready():
    print(f"{FG.lightcyan}Server started to listen for connections at {RESET}{server.host}{FG.darkgray}:{RESET}{server.port}")

@server.register
def on_connect(client: net.TCPClientConnection):
    print(f"{FG.lightgreen}New connection from {RESET}{client.address}{FG.darkgray}:{RESET}{client.port} {FG.lightgreen}is given ID {RESET}{client.id}")

@server.register
def on_disconnect(client: net.TCPClientConnection):
    print(f"{FG.orange}Client{RESET}#{client.id} {FG.orange}disconnected.{RESET}")

@server.register
def on_packet(packet: net.common.Packet, client: net.TCPClientConnection):
    data = packet.data.decode()
    print(f"{FG.magenta}New message from client{RESET}#{client.id} {FG.darkgray}>>{RESET} {data}")

server.start()

input()

server.stop()
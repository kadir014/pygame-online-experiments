import net
from terminal import FG, RESET


client = net.TCPClient(net.common.LOCALHOST, 65432)

@client.register
def on_connect():
    print("Connected")

@client.register
def on_disconnect():
    print("Disconnected")

@client.register
def on_packet(packet: net.common.Packet):
    print(f"Packet: {packet.data.decode()}")

client.connect()
client.outgoing.put(b"hello!")

input()

client.disconnect()
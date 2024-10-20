import json
from contextlib import contextmanager
from time import perf_counter
from random import randint, choice

import pygame

import net


COLORS = {
    "Red": (255, 0, 0),
    "Orange": (255, 128, 0),
    "Yellow": (255, 255, 0),
    "Green": (0, 255, 0),
    "Blue": (0, 0, 255), 
    "Purple": (128, 0, 255)
}

class Player:
    def __init__(self):
        self.position = pygame.Vector2(randint(100, 500 - 100), randint(100, 500 - 100))
        self.size = (30, 30)
        color_key = choice(list(COLORS.keys()))
        self.color = COLORS[color_key]
        self.name = f"Player{color_key}{randint(100, 999)}"

    def draw(self, game: "Game", other: bool = False) -> None:
        player_rect = pygame.Rect(self.position, self.size)
        pygame.draw.rect(game.display, (0, 0, 0), player_rect.inflate(2, 2))
        pygame.draw.rect(game.display, self.color, player_rect)

        name_col = (0, 0, 0) if not other else (160, 160, 160)
        name_surf = game.fonts["NotoSans"].render(self.name, True, name_col)
        name_pos = pygame.Vector2(self.position.x - (name_surf.width / 2 - self.size[0] / 2), self.position.y - 30)
        game.display.blit(name_surf, name_pos)

        border_rect = name_surf.get_rect().inflate(8, 4)
        border_rect.topleft += name_pos
        pygame.draw.rect(game.display, name_col, border_rect, 1, border_radius=7)

    def serialize(self) -> str:
        return json.dumps({"name": self.name, "color": self.color})


def interpolate(x1: float, x2: float, y1: float, y2: float, x: float):
    """ Perform linear interpolation for x between (x1,y1) and (x2,y2) """

    return ((y2 - y1) * x + x2 * y1 - x1 * y2) / (x2 - x1)


class Game:
    """
    Top-level game class.
    """

    def __init__(self) -> None:
        # Pygame stuff
        pygame.init()
        self.window_width, self.window_height = 500, 500
        self.display = pygame.display.set_mode((self.window_width, self.window_height))
        pygame.display.set_caption("Pygame-CE Game")
        self.clock = pygame.time.Clock()
        self.is_running = False

        self.max_fps = 60
        self.fps = self.max_fps
        self.dt = 1.0 / self.fps
        self.events = []
        self.mouse = pygame.Vector2()

        self.fonts = {
            "FiraCode": pygame.Font("assets/FiraCode-Regular.ttf", 12),
            "NotoSans": pygame.Font("assets/NotoSans-Regular.ttf", 14)
        }

        # Version info
        self.pygame_version = pygame.version.ver
        self.sdl_version = ".".join((str(v) for v in pygame.get_sdl_version()))

        # Profiling stuff
        self.stats = {
            "render": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "tick": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "network": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "frame": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "fps": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []}
        }
        self.stat_accumulate = 30
        self.stat_drawing = 1

        self.player = Player()
        self.players = {}
        self.player_poss0 = []
        self.player_poss = []
        self.server_tick = perf_counter()
        self.server_last_tick = 0
        self.interpolation = False

        self.client = net.TCPClient("127.0.0.1", 65432)

        self.client.register(self.on_connect)
        self.client.register(self.on_disconnect)
        self.client.register(self.on_packet)

        self.client.connect()

    def on_connect(self):
        print(f"Successfully connected to {self.client.host}:{self.client.port}")
        self.client._outgoing.put(f"_{self.player.serialize()}".encode())

    def on_disconnect(self):
        print("Disconnected")
        # In case this happened from a network error
        self.is_running = False

    def on_packet(self, packet: net.common.Packet):
        data = packet.data.decode()

        if data.startswith("_"):
            deserialized = json.loads(data[1:])
            id_ = int(deserialized["id"])
            self.players[id_] = Player()
            self.players[id_].name = deserialized["name"]
            self.players[id_].color = deserialized["color"]
            print(f"Client#{id_} data received: {self.players[id_].name}")

        else:
            self.server_last_tick = perf_counter() - self.server_tick
            self.server_tick = perf_counter()

            self.player_poss0.clear()
            for pos in self.player_poss: self.player_poss0.append(pos)

            self.player_poss.clear()

            jsondata = json.loads(data)

            for id_ in jsondata:
                pid = int(id_)
                # Player data has not yet received
                if pid not in self.players: continue

                pos = jsondata[id_]
                x, y = float(pos[0]), float(pos[1])
                self.players[pid].position = pygame.Vector2(x, y)

    @contextmanager
    def profile(self, stat: str):
        """ Profile code. """

        start = perf_counter()
        
        try: yield None

        finally:
            elapsed = perf_counter() - start
            self.accumulate(stat, elapsed)

    def accumulate(self, stat: str, value: float) -> None:
        """ Accumulate stat value. """

        acc = self.stats[stat]["acc"]
        acc.append(value)

        if len(acc) > self.stat_accumulate:
            acc.pop(0)

            self.stats[stat]["avg"] = sum(acc) / len(acc)
            self.stats[stat]["min"] = min(acc)
            self.stats[stat]["max"] = max(acc)

    def handle_events(self) -> None:
        """ Handle Pygame events. """

        for event in self.events:
            if event.type == pygame.QUIT:
                self.stop()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F1:
                    self.interpolation = not self.interpolation

    def stop(self) -> None:
        """ Stop the app. """

        self.is_running = False
        self.client.disconnect()

    def run(self) -> None:
        """ Run the game. """

        self.is_running = True

        while self.is_running:
            self.frame()

    def frame(self) -> None:
        """ One game frame. """

        with self.profile("frame"):
            self.dt = self.clock.tick(self.max_fps) / 1000.0
            self.fps = self.clock.get_fps()
            if self.fps == float("inf"): self.fps = 0
            self.accumulate("fps", self.fps)

            self.mouse = pygame.Vector2(*pygame.mouse.get_pos())
            self.events = pygame.event.get()
            self.handle_events()

            with self.profile("tick"):
                self.update()

            with self.profile("network"):
                x, y = int(self.player.position.x), int(self.player.position.y)
                #self.client.send_raw(f"{x},{y}".encode())
                self.client._outgoing.put(f"{x},{y}".encode())

            with self.profile("render"):
                self.render()

    def update(self) -> None:
        """ Update one tick frame. """

        keys = pygame.key.get_pressed()
        speed = 300

        if keys[pygame.K_a]: self.player.position.x -= speed * self.dt
        if keys[pygame.K_d]: self.player.position.x += speed * self.dt
        if keys[pygame.K_w]: self.player.position.y -= speed * self.dt
        if keys[pygame.K_s]: self.player.position.y += speed * self.dt

    def render(self) -> None:
        """ Render one game frame. """
        
        self.display.fill((255, 255, 255))

        self.player.draw(self)
        
        if self.interpolation:
            if len(self.player_poss) == len(self.player_poss0):
                for i, pos in enumerate(self.player_poss):
                    pos0 = pygame.Vector2(*self.player_poss0[i])
                    pos = pygame.Vector2(*pos)

                    dir = pos - pos0
                    dist = dir.length()

                    if dist != 0:
                        t0 = self.server_tick
                        t1 = self.server_tick + self.server_last_tick
                        #print(self.server_last_tick)

                        elapsed = perf_counter()

                        curr_dist = interpolate(t0, t1, 0, dist, elapsed)

                        pos0 += dir.normalize() * curr_dist

                    pygame.draw.rect(self.display, (255, 0, 0), (pos0, (30, 30)))

        else:
            #for pos in self.player_poss:
            #    pygame.draw.rect(self.display, (255, 0, 0), (pos, (30, 30)))

            for id_ in self.players:
                player = self.players[id_]
                player.draw(self, other=True)

        lines = (
            f"         avg    lo     hi",
            f"FPS:     {round(self.stats['fps']['avg'])}    {round(self.stats['fps']['min'])}    {round(self.stats['fps']['max'])}",
            f"Frame:   {round(self.stats['frame']['avg'] * 1000, 1)}    {round(self.stats['frame']['min'] * 1000, 2)}    {round(self.stats['frame']['max'] * 1000, 2)} ms",
            f"Render:  {round(self.stats['render']['avg'] * 1000, 1)}    {round(self.stats['render']['min'] * 1000, 2)}    {round(self.stats['render']['max'] * 1000, 2)} ms",
            f"Tick:    {round(self.stats['tick']['avg'] * 1000, 1)}    {round(self.stats['tick']['min'] * 1000, 2)}    {round(self.stats['tick']['max'] * 1000, 2)} ms",
            f"Network: {round(self.stats['network']['avg'] * 1000, 1)}    {round(self.stats['network']['min'] * 1000, 2)}    {round(self.stats['network']['max'] * 1000, 2)} ms",
            f"Latency: {round(self.client.latency * 1000, 2)}ms",
            f"Connection: L={round(self.client.connection_profile.listener_time * 1000, 2)}ms "
            f"P={round(self.client.connection_profile.processer_time * 1000, 2)}ms "
            f"S={round(self.client.connection_profile.sender_time * 1000, 2)}ms",
            f"Interpolation: {('disabled', 'enabled')[self.interpolation]}"
        )
        for i, line in enumerate(lines):
            self.display.blit(self.fonts["FiraCode"].render(line, True, (0, 0, 0)), (5, 5 + 16 * i))

        pygame.display.flip()


if __name__ == "__main__":
    game = Game()
    game.run()

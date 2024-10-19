import sys
import asyncio
from contextlib import contextmanager
from time import perf_counter
from random import randint

import pygame

import net


def is_web() -> bool:
    """ Check if the application is running on web. """
    return sys.platform.lower() == "emscripten"


class Player:
    def __init__(self):
        self.pos = pygame.Vector2(randint(100, 500-100), randint(100, 500-100))


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

        self.max_fps = 165
        self.fps = self.max_fps
        self.dt = 1.0 / self.fps
        self.events = []
        self.mouse = pygame.Vector2()

        self.font = pygame.Font("assets/NotoSans-Regular.ttf", 14)

        # Version info
        self.pygame_version = pygame.version.ver
        self.sdl_version = ".".join((str(v) for v in pygame.get_sdl_version()))
        self.platform = ("Desktop", "Web")[is_web()]

        # Profiling stuff
        self.stats = {
            "render": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "update": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "network": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "frame": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []},
            "fps": {"avg": 0.0, "min": 0.0, "max": 0.0, "acc": []}
        }
        self.stat_accumulate = 30
        self.stat_drawing = 1

        self.player = Player()
        self.player_poss0 = []
        self.player_poss = []
        self.server_tick = perf_counter()
        self.server_last_tick = 0
        self.interpolation = True

        self.client = net.TCPClient("127.0.0.1", 65432)

        self.client.event_manager.register(self.on_connect)
        self.client.event_manager.register(self.on_disconnect)
        self.client.event_manager.register(self.on_packet)

        self.client.start()

    def on_connect(self):
        print(f"Successfully connected to {self.client.address}:{self.client.port}")

    def on_disconnect(self):
        print("Disconnected")

    def on_packet(self, packet: net.Packet):
        self.server_last_tick = perf_counter() - self.server_tick
        self.server_tick = perf_counter()

        self.player_poss0.clear()
        for pos in self.player_poss: self.player_poss0.append(pos)

        self.player_poss.clear()

        data = packet.data.decode().split(";")

        for d in data:
            pos = d.split(",")
            x, y = int(pos[0]), int(pos[1])
            self.player_poss.append((x, y))

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
            self.tick()

    async def run_async(self):
        """ Run the game asynchronously for web. """

        self.is_running = True

        while self.is_running:
            self.tick()

            await asyncio.sleep(0)

    def tick(self) -> None:
        """ One game frame. """

        with self.profile("frame"):
            self.dt = self.clock.tick(self.max_fps) / 1000.0
            self.fps = self.clock.get_fps()
            if self.fps == float("inf"): self.fps = 0
            self.accumulate("fps", self.fps)

            self.mouse = pygame.Vector2(*pygame.mouse.get_pos())
            self.events = pygame.event.get()
            self.handle_events()

            with self.profile("update"):
                self.update()

            with self.profile("network"):
                x, y = int(self.player.pos.x), int(self.player.pos.y)
                #self.client.send_raw(f"{x},{y}".encode())
                self.client.outgoing.put(f"{x},{y}".encode())

            with self.profile("render"):
                self.render()

    def update(self) -> None:
        """ Update one game frame. """

        keys = pygame.key.get_pressed()
        speed = 600

        if keys[pygame.K_a]: self.player.pos.x -= speed * self.dt
        if keys[pygame.K_d]: self.player.pos.x += speed * self.dt
        if keys[pygame.K_w]: self.player.pos.y -= speed * self.dt
        if keys[pygame.K_s]: self.player.pos.y += speed * self.dt

    def render(self) -> None:
        """ Render one game frame. """
        
        self.display.fill((255, 255, 255))

        pygame.draw.rect(self.display, (0, 0, 255), (self.player.pos, (30, 30)))
        
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
            for pos in self.player_poss:
                pygame.draw.rect(self.display, (255, 0, 0), (pos, (30, 30)))

        self.display.blit(self.font.render(f"FPS: {round(self.fps)}", True, (0,0,0)), (5, 5+16*0))
        self.display.blit(self.font.render(f"Network: {round(self.stats['network']['avg'] * 1000, 2)}ms", True, (0,0,0)), (5, 5+16*1))
        self.display.blit(self.font.render(f"Latency: {round(self.client.latency * 1000, 2)}ms", True, (0,0,0)), (5, 5+16*2))
        self.display.blit(self.font.render(f"Listener: {round(self.client.listener_time * 1000, 2)}ms", True, (0,0,0)), (5, 5+16*3))
        self.display.blit(self.font.render(f"Processer: {round(self.client.processer_time * 1000, 2)}ms", True, (0,0,0)), (5, 5+16*4))
        self.display.blit(self.font.render(f"Sender: {round(self.client.sender_time * 1000, 2)}ms", True, (0,0,0)), (5, 5+16*5))
        self.display.blit(self.font.render(f"Interpolation: {self.interpolation}", True, (0,0,0)), (5, 5+16*6))

        pygame.display.flip()


if __name__ == "__main__":
    game = Game()

    if game.platform == "Web":
        asyncio.run(game.run_async())

    else:
        game.run()

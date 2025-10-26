import random
import hashlib
import time
import math
import json
import os
from enum import Enum
from collections import deque
from typing import List, Tuple, Optional, Dict
from kivy.config import Config as KivyConfig

KivyConfig.set("graphics", "resizable", False)
KivyConfig.set("graphics", "width", "640")
KivyConfig.set("graphics", "height", "682")
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import (
    ScreenManager,
    Screen,
    FadeTransition,
    SlideTransition,
)
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Rectangle, Line, RoundedRectangle, Ellipse
from kivy.clock import Clock
from kivy.animation import Animation
from kivy.core.audio import SoundLoader
from kivy.core.window import Window
from kivy.properties import (
    NumericProperty,
    BooleanProperty,
    StringProperty,
    ListProperty,
)
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.uix.image import Image
from kivy.uix.anchorlayout import AnchorLayout


class GameState(Enum):
    MENU = "menu"
    BETTING = "betting"
    FLYING = "flying"
    CRASHED = "crashed"
    RESULT = "result"


class Config:
    INITIAL_BALANCE = 100
    MIN_BET = 10
    BET_PRESETS = [10, 50, 100, 500]
    MAX_PARTICLES = 800
    TARGET_FPS = 60
    CRASH_MAX_RANGE = 15.0
    CRASH_SKEW = 2.5
    SPECIAL_CHANCE = 0.01
    SPECIAL_MIN = 10.0
    SPECIAL_MAX = 50.0
    GROWTH_FACTOR = 0.05
    GROWTH_EXPONENT = 1.3
    FLIGHT_SAMPLES = 400
    PLANE_START_X = 1150
    PLANE_START_Y = 330
    STATS_FILE = "shiiiuuuu_stats.json"


Builder.load_string("""
<StyledButton@Button>:
    background_color: 0, 0, 0, 0
    canvas.before:
        Color:
            rgba: self.bg_color if hasattr(self, 'bg_color') else (0.2, 0.6, 0.8, 0.8)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(20),]
    font_size: '20sp'
    bold: True
    color: 1, 1, 1, 1

<StyledTextInput@TextInput>:
    background_color: 0, 0, 0, 0
    foreground_color: 1, 1, 1, 0.9
    cursor_color: 1, 1, 1, 1
    font_size: '18sp'
    halign: 'center'
    padding: [dp(10), (self.height - self.line_height)/2]
    canvas.before:
        Color:
            rgba: 0.1, 0.1, 0.2, 0.7
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12),]
""")


class Particle:
    def __init__(self):
        self.reset()

    def reset(self):
        self.active = False
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.lifetime = 0.0
        self.max_lifetime = 1.0
        self.size = 3.0
        self.initial_size = 3.0
        self.r = 1.0
        self.g = 1.0
        self.b = 0.8
        self.a = 0.8
        self.initial_a = 0.8

    def init(
        self,
        x: float,
        y: float,
        vx: float,
        vy: float,
        lifetime: float,
        size: float,
        color: Tuple[float, float, float, float],
    ):
        self.active = True
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.lifetime = lifetime
        self.max_lifetime = lifetime
        self.size = size
        self.initial_size = size
        self.r, self.g, self.b, self.a = color
        self.initial_a = color[3]

    def update(self, dt: float):
        if not self.active:
            return
        self.lifetime -= dt
        if self.lifetime <= 0:
            self.active = False
            return
        self.x += self.vx * dt * 60
        self.y += self.vy * dt * 60
        fade = max(0, self.lifetime / self.max_lifetime)
        self.a = self.initial_a * fade
        self.size = self.initial_size * fade


class ParticlePool:
    def __init__(self, canvas, max_particles: int = Config.MAX_PARTICLES):
        self.canvas = canvas
        self.particles: List[Particle] = [Particle() for _ in range(max_particles)]
        self.visuals: List[Tuple[Color, Ellipse]] = []
        for _ in range(max_particles):
            with self.canvas:
                color_inst = Color(1, 1, 1, 0)
                ellipse_inst = Ellipse(pos=(0, 0), size=(0, 0))
                self.visuals.append((color_inst, ellipse_inst))

    def emit(
        self,
        x: float,
        y: float,
        count: int,
        color: Tuple[float, float, float, float],
        lifetime_range: Tuple[float, float],
        size_range: Tuple[float, float],
        velocity_range: Tuple[float, float],
    ):
        emitted = 0
        for i, particle in enumerate(self.particles):
            if emitted >= count:
                break
            if not particle.active:
                lt = random.uniform(*lifetime_range)
                sz = random.uniform(*size_range)
                vx = random.uniform(*velocity_range)
                vy = random.uniform(*velocity_range)
                particle.init(x, y, vx, vy, lt, sz, color)
                emitted += 1

    def update(self, dt: float):
        for i, particle in enumerate(self.particles):
            if particle.active:
                particle.update(dt)
                color_inst, ellipse_inst = self.visuals[i]
                color_inst.rgba = (particle.r, particle.g, particle.b, particle.a)
                ellipse_inst.pos = (
                    particle.x - particle.size / 2,
                    particle.y - particle.size / 2,
                )
                ellipse_inst.size = (particle.size, particle.size)
            else:
                color_inst, ellipse_inst = self.visuals[i]
                ellipse_inst.size = (0, 0)


class AssetManager:
    def __init__(self):
        self.sounds: Dict[str, Optional[object]] = {}
        self._load_sounds()

    def _load_sounds(self):
        sound_files = {
            "bet": "bet.wav",
            "cashout": "cash_out.wav",
            "crash": "crash.wav",
        }
        for key, filename in sound_files.items():
            try:
                sound = SoundLoader.load(filename)
                if sound:
                    sound.volume = 0.7
                self.sounds[key] = sound
            except:
                self.sounds[key] = None

    def play_sound(self, key: str):
        sound = self.sounds.get(key)
        if sound:
            sound.play()


class StateManager:
    def __init__(self):
        self.state = GameState.BETTING
        self.balance = Config.INITIAL_BALANCE
        self.current_bet = 0
        self.multiplier = 1.0
        self.crash_point = 0.0
        self.start_time = 0.0
        self.history: deque = deque(maxlen=5)
        self.stats = self._load_stats()
        self.cooldown_bet = False
        self.cooldown_cashout = False

    def _load_stats(self) -> Dict:
        default_stats = {
            "total_games": 0,
            "wins": 0,
            "losses": 0,
            "highest_multiplier": 1.0,
            "biggest_win": 0,
        }
        if os.path.exists(Config.STATS_FILE):
            try:
                with open(Config.STATS_FILE, "r") as f:
                    return json.load(f)
            except:
                return default_stats
        return default_stats

    def save_stats(self):
        try:
            with open(Config.STATS_FILE, "w") as f:
                json.dump(self.stats, f)
        except:
            pass

    def reset_balance(self):
        self.balance = Config.INITIAL_BALANCE
        self.history.clear()

    def can_place_bet(self, amount: int) -> bool:
        return (
            self.state == GameState.BETTING
            and not self.cooldown_bet
            and amount >= Config.MIN_BET
            and amount <= self.balance
        )

    def place_bet(self, amount: int):
        self.current_bet = amount
        self.balance -= amount
        self.state = GameState.FLYING
        self.multiplier = 1.0
        self.start_time = time.time()
        self.stats["total_games"] += 1
        self.generate_crash_point()
        self.cooldown_bet = True

    def generate_crash_point(self):
        seed = hashlib.sha256(str(time.time() + random.random()).encode()).hexdigest()
        random.seed(seed)
        raw = random.random()
        self.crash_point = 1.0 + (raw**Config.CRASH_SKEW) * Config.CRASH_MAX_RANGE
        if random.random() < Config.SPECIAL_CHANCE:
            self.crash_point = random.uniform(Config.SPECIAL_MIN, Config.SPECIAL_MAX)

    def update_multiplier(self):
        if self.state != GameState.FLYING:
            return
        elapsed = time.time() - self.start_time
        self.multiplier = 1.0 + Config.GROWTH_FACTOR * (elapsed**Config.GROWTH_EXPONENT)

    def check_crash(self) -> bool:
        if self.state == GameState.FLYING and self.multiplier >= self.crash_point:
            self.state = GameState.CRASHED
            self.stats["losses"] += 1
            self.history.append({"multiplier": self.multiplier, "success": False})
            self.save_stats()
            return True
        return False

    def can_cash_out(self) -> bool:
        return self.state == GameState.FLYING and not self.cooldown_cashout

    def cash_out(self) -> int:
        winnings = int(self.current_bet * self.multiplier)
        self.balance += winnings
        profit = winnings - self.current_bet
        self.stats["wins"] += 1
        self.stats["highest_multiplier"] = max(
            self.stats["highest_multiplier"], self.multiplier
        )
        self.stats["biggest_win"] = max(self.stats["biggest_win"], profit)
        self.history.append({"multiplier": self.multiplier, "success": True})
        self.state = GameState.RESULT
        self.cooldown_cashout = True
        self.save_stats()
        return winnings

    def reset_to_betting(self):
        self.state = GameState.BETTING
        self.multiplier = 1.0
        self.current_bet = 0


class GameEngine:
    def __init__(self, state_manager: StateManager, assets: AssetManager):
        self.state = state_manager
        self.assets = assets
        self.flight_path: List[Tuple[float, float]] = []
        self.current_path_index = 0
        self.plane_x = Config.PLANE_START_X
        self.plane_y = Config.PLANE_START_Y
        self.plane_angle = 0.0

    def generate_flight_path(self, width: float, height: float):
        self.flight_path = []
        for i in range(Config.FLIGHT_SAMPLES):
            t = i / Config.FLIGHT_SAMPLES
            x = Config.PLANE_START_X + t * -475

            if t < 0.15:
                y = Config.PLANE_START_Y + t * 2000
            else:
                base_y = Config.PLANE_START_Y + 300 + (t - 0.15) * 225
                y = base_y + 75 * math.sin((t - 0.15) * 15)

            self.flight_path.append((x, y))
        self.current_path_index = 0

    def update_plane_position(self):
        if self.state.state != GameState.FLYING:
            return

        if self.current_path_index < len(self.flight_path):
            self.current_path_index = min(
                len(self.flight_path) - 1, self.current_path_index + 1
            )
            self.plane_x, self.plane_y = self.flight_path[self.current_path_index]

    def get_multiplier_color(self) -> Tuple[float, float, float, float]:
        if self.state.multiplier < 2.0:
            return (0.2, 0.8, 0.2, 0.9)
        elif self.state.multiplier < 5.0:
            return (1, 0.7, 0.2, 0.9)
        return (1, 0.2, 0.2, 0.9)

    def reset_plane(self):
        self.plane_x = Config.PLANE_START_X
        self.plane_y = Config.PLANE_START_Y
        self.plane_angle = 0.0
        self.current_path_index = 0


class StartScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.create_background()
        self.create_ui()

    def create_background(self):
        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1)
            Rectangle(size=(5000, 5000), pos=(0, 0))
            Color(1, 1, 1, 0.8)
            for _ in range(100):
                x = random.randint(0, Window.width)
                y = random.randint(0, Window.height)
                size = random.uniform(2, 4)
                Ellipse(pos=(x, y), size=(size, size))

    def create_ui(self):
        layout = BoxLayout(orientation="vertical", padding=dp(40), spacing=dp(25))

        title = Label(
            text="SHIIIUUUU",
            font_size="60sp",
            color=(1, 1, 1, 1),
            bold=True,
            size_hint_y=0.4,
        )
        layout.add_widget(title)

        button_layout = BoxLayout(
            orientation="vertical", spacing=dp(25), size_hint_y=0.6
        )

        btn_start = self._create_button(
            "START GAME", (0.2, 0.7, 0.3, 0.9), self.start_game
        )
        btn_stats = self._create_button("STATS", (0.3, 0.5, 0.8, 0.9), self.show_stats)
        btn_credits = self._create_button(
            "CREDITS", (0.6, 0.3, 0.7, 0.9), self.show_credits
        )
        btn_exit = self._create_button("EXIT", (0.8, 0.2, 0.2, 0.9), self.exit_game)

        button_layout.add_widget(btn_start)
        button_layout.add_widget(btn_stats)
        button_layout.add_widget(btn_credits)
        button_layout.add_widget(btn_exit)

        layout.add_widget(button_layout)
        self.add_widget(layout)

    def _create_button(
        self, text: str, color: Tuple[float, float, float, float], callback
    ):
        btn = Button(
            text=text,
            font_size="26sp",
            size_hint_y=None,
            height=dp(90),
            bold=True,
            background_color=(0, 0, 0, 0),
        )
        btn.bg_color = color
        btn.bind(on_press=callback)

        with btn.canvas.before:
            Color(*color)
            RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    dp(12),
                ],
            )

        def update_bg(instance, value):
            btn.canvas.before.clear()
            with btn.canvas.before:
                Color(*color)
                RoundedRectangle(
                    pos=instance.pos,
                    size=instance.size,
                    radius=[
                        dp(12),
                    ],
                )

        btn.bind(pos=update_bg, size=update_bg)
        return btn

    def start_game(self, instance):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "game"

    def show_stats(self, instance):
        stats_screen = self.manager.get_screen("stats")
        stats_screen.update_stats()
        self.manager.transition = SlideTransition(direction="up")
        self.manager.current = "stats"

    def show_credits(self, instance):
        self.manager.transition = SlideTransition(direction="up")
        self.manager.current = "credits"

    def exit_game(self, instance):
        App.get_running_app().stop()


class StatsScreen(Screen):
    def __init__(self, state_manager: StateManager, **kwargs):
        super().__init__(**kwargs)
        self.state = state_manager
        self.create_background()
        self.create_ui()

    def create_background(self):
        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1)
            Rectangle(size=(5000, 5000), pos=(0, 0))

    def create_ui(self):
        self.layout = BoxLayout(orientation="vertical", padding=dp(40), spacing=dp(25))

        title = Label(
            text="STATS",
            font_size="60sp",
            color=(1, 1, 1, 1),
            bold=True,
            size_hint_y=0.2,
        )
        self.layout.add_widget(title)

        self.stats_content = BoxLayout(
            orientation="vertical", spacing=dp(20), size_hint_y=0.6
        )
        self.layout.add_widget(self.stats_content)

        btn_back = self._create_back_button()
        self.layout.add_widget(btn_back)

        self.add_widget(self.layout)

    def _create_back_button(self):
        btn = Button(
            text="BACK",
            size_hint=(0.5, None),
            font_size="32sp",
            height=dp(80),
            pos_hint={"center_x": 0.5},
            bold=True,
            background_color=(0, 0, 0, 0),
        )
        color = (0.3, 0.4, 0.8, 0.9)

        with btn.canvas.before:
            Color(*color)
            RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    dp(12),
                ],
            )

        def update_bg(instance, value):
            btn.canvas.before.clear()
            with btn.canvas.before:
                Color(*color)
                RoundedRectangle(
                    pos=instance.pos,
                    size=instance.size,
                    radius=[
                        dp(12),
                    ],
                )

        btn.bind(pos=update_bg, size=update_bg)
        btn.bind(on_press=self.go_back)
        return btn

    def update_stats(self):
        self.stats_content.clear_widgets()
        stats = self.state.stats
        for key, value in stats.items():
            if key == "highest_multiplier":
                text = f"{key.replace('_', ' ').title()}: {value:.2f}x"
            elif key == "biggest_win":
                text = f"{key.replace('_', ' ').title()}: ${value:.2f}"
            else:
                text = f"{key.replace('_', ' ').title()}: {value}"
            label = Label(text=text, font_size="24sp", color=(1, 1, 1, 0.9), bold=True)
            self.stats_content.add_widget(label)

    def go_back(self, instance):
        self.manager.transition = SlideTransition(direction="down")
        self.manager.current = "start"


class CreditsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.create_background()
        self.create_ui()

    def create_background(self):
        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1)
            Rectangle(size=(5000, 5000), pos=(0, 0))

    def create_ui(self):
        layout = BoxLayout(orientation="vertical", padding=dp(40), spacing=dp(25))

        title = Label(
            text="CREDITS",
            font_size="50sp",
            color=(1, 1, 1, 1),
            bold=True,
            size_hint_y=0.2,
        )
        layout.add_widget(title)

        credits_content = BoxLayout(
            orientation="vertical", spacing=dp(15), size_hint_y=0.6
        )

        credits_data = [
            ("Developer: Shreesh Bhattarai", "24sp"),
            ("Version: 1.0", "20sp"),
            ("Built with Kivy Framework", "20sp"),
            ("© 2025 All Rights Reserved", "20sp"),
            ("Sound Assets: WavSource.com", "20sp"),
        ]

        for text, font_size in credits_data:
            label = Label(text=text, font_size=font_size, color=(1, 1, 1, 1))
            credits_content.add_widget(label)

        layout.add_widget(credits_content)

        btn_back = self._create_back_button()
        layout.add_widget(btn_back)

        self.add_widget(layout)

    def _create_back_button(self):
        btn = Button(
            text="BACK",
            size_hint=(0.5, None),
            font_size="32sp",
            height=dp(80),
            pos_hint={"center_x": 0.5},
            bold=True,
            background_color=(0, 0, 0, 0),
        )
        color = (0.3, 0.4, 0.8, 0.9)

        with btn.canvas.before:
            Color(*color)
            RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    dp(12),
                ],
            )

        def update_bg(instance, value):
            btn.canvas.before.clear()
            with btn.canvas.before:
                Color(*color)
                RoundedRectangle(
                    pos=instance.pos,
                    size=instance.size,
                    radius=[
                        dp(12),
                    ],
                )

        btn.bind(pos=update_bg, size=update_bg)
        btn.bind(on_press=self.go_back)
        return btn

    def go_back(self, instance):
        self.manager.transition = SlideTransition(direction="down")
        self.manager.current = "start"


class GameScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state_manager = StateManager()
        self.assets = AssetManager()
        self.engine = GameEngine(self.state_manager, self.assets)
        self.particles = None
        self.game_view = GameView(self.state_manager, self.engine, self.assets)
        self.add_widget(self.game_view)


class GameView(FloatLayout):
    def __init__(
        self,
        state_manager: StateManager,
        engine: GameEngine,
        assets: AssetManager,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.state = state_manager
        self.engine = engine
        self.assets = assets
        self.particles = None

        self.create_background()
        self.create_game_area()
        self.create_ui()

        Clock.schedule_interval(self.update_game, 1.0 / Config.TARGET_FPS)

    def create_background(self):
        with self.canvas.before:
            Color(0.05, 0.05, 0.15, 1)
            self.bg = Rectangle(pos=self.pos, size=self.size)
            Color(1, 1, 1, 0.8)
            for _ in range(120):
                x = random.randint(0, Window.width)
                y = random.randint(0, Window.height)
                size = random.uniform(2, 4)
                Ellipse(pos=(x, y), size=(size, size))
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *args):
        self.bg.pos = self.pos
        self.bg.size = self.size

    def create_game_area(self):
        self.plane_image = Image(
            source="plane_icon.png",
            size_hint=(None, None),
            size=(dp(80), dp(80)),
            allow_stretch=True,
            keep_ratio=True,
        )
        self.plane_image.center = (Config.PLANE_START_X, Config.PLANE_START_Y)
        self.add_widget(self.plane_image)

        self.multiplier_label = Label(
            text="1.00x",
            font_size="84sp",
            color=(1, 1, 1, 0.9),
            bold=True,
            size_hint=(None, None),
        )
        self.multiplier_label.pos = ((self.width + 100) / 2, self.height - 130)
        self.bind(
            size=lambda *args: setattr(
                self.multiplier_label,
                "pos",
                ((self.width + 100) / 2, self.height - 130),
            )
        )
        self.add_widget(self.multiplier_label)

        self.crash_label = Label(
            text="",
            font_size="36sp",
            color=(1, 0.1, 0.1, 1),
            bold=True,
            pos_hint={"center_x": 0.5, "center_y": 0.80},
            opacity=0,
        )
        self.add_widget(self.crash_label)
        self.particles = ParticlePool(self.canvas)

    def create_ui(self):
        self.balance_label = Label(
            text=f"Balance: ${self.state.balance:.2f}",
            font_size="21sp",
            color=(1, 1, 1, 0.9),
            bold=True,
            size_hint=(None, None),
            halign="left",
        )
        self.balance_label.text_size = (400, None)
        self.balance_label.pos = (160, self.height - 100)
        self.bind(
            height=lambda *args: setattr(
                self.balance_label, "pos", (160, self.height - 100)
            )
        )
        self.add_widget(self.balance_label)

        self.potential_label = Label(
            text="Potential: $0.00",
            font_size="21sp",
            color=(0.2, 1, 0.2, 0.9),
            bold=True,
            size_hint=(None, None),
            halign="left",
        )
        self.potential_label.text_size = (400, None)
        self.potential_label.pos = (160, self.height - 175)
        self.bind(
            height=lambda *args: setattr(
                self.potential_label, "pos", (160, self.height - 175)
            )
        )
        self.add_widget(self.potential_label)

        reset_btn = self._create_styled_btn(
            "RESET BALANCE", (0.7, 0.3, 0.3, 0.9), (400, 100)
        )
        reset_btn.pos = (30, 30)
        self.bind(size=lambda *args: setattr(reset_btn, "pos", (30, 30)))
        reset_btn.bind(on_press=self.reset_balance)
        self.add_widget(reset_btn)

        back_btn = self._create_styled_btn("BACK", (0.3, 0.4, 0.8, 0.9), (150, 120))
        back_btn.pos = (self.width - 165, self.height - 140)
        self.bind(
            size=lambda *args: setattr(
                back_btn, "pos", (self.width - 165, self.height - 140)
            )
        )
        back_btn.bind(on_press=self.go_back)
        self.add_widget(back_btn)

        self.create_controls()
        self.create_history()

    def _create_styled_btn(self, text, color, size):
        btn = Button(
            text=text,
            size_hint=(None, None),
            size=size,
            background_color=(0, 0, 0, 0),
            bold=True,
            font_size="24sp",
        )
        with btn.canvas.before:
            Color(*color)
            btn.bg_rect = RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    15,
                ],
            )

        def update_bg(instance, value):
            btn.bg_rect.pos = instance.pos
            btn.bg_rect.size = instance.size

        btn.bind(pos=update_bg, size=update_bg)
        return btn

    def create_controls(self):
        bet_label = Label(
            text="Bet Amount:",
            font_size="24sp",
            color=(1, 1, 1, 0.9),
            bold=True,
            size_hint=(None, None),
            size=(250, 100),
        )
        bet_label.pos = (40, 150)
        self.add_widget(bet_label)

        self.bet_input = TextInput(
            text="100",
            input_filter="int",
            size_hint=(None, None),
            size=(120, 100),
            background_color=(1, 1, 1, 1),
            foreground_color=(0, 0, 0, 1),
            font_size="24sp",
            halign="center",
            padding=[10, 20],
        )
        self.bet_input.pos = (310, 150)
        self.bet_input.bind(text=lambda *args: self.update_button_states())
        self.add_widget(self.bet_input)

        btn_increase = self._create_bet_button("+", (0.2, 0.7, 0.2, 0.9), (200, 100))
        btn_increase.pos = (450, 150)
        btn_increase.bind(on_press=lambda x: self.adjust_bet(10))
        self.add_widget(btn_increase)

        btn_decrease = self._create_bet_button("-", (0.7, 0.2, 0.2, 0.9), (200, 100))
        btn_decrease.pos = (680, 150)
        btn_decrease.bind(on_press=lambda x: self.adjust_bet(-10))
        self.add_widget(btn_decrease)

        preset_positions = [0, 110, 220, 330]
        for i, preset in enumerate(Config.BET_PRESETS):
            btn = self._create_bet_button(str(preset), (0.3, 0.4, 0.6, 0.9), (100, 100))
            btn.pos = (preset_positions[i] + 450, 30)
            btn.bind(on_press=lambda x, p=preset: self.set_bet(p))
            self.add_widget(btn)

        self.place_bet_btn = self._create_action_button(
            "PLACE BET", (0.1, 0.7, 0.2, 0.9), (350, 100)
        )
        self.place_bet_btn.pos = (900, 150)
        self.place_bet_btn.bind(on_press=self.place_bet)
        self.add_widget(self.place_bet_btn)

        self.cash_out_btn = self._create_action_button(
            "CASH OUT", (0.8, 0.1, 0.1, 0.9), (350, 100)
        )
        self.cash_out_btn.pos = (900, 30)
        self.cash_out_btn.disabled = True
        self.cash_out_btn.bind(on_press=self.cash_out)
        self.add_widget(self.cash_out_btn)

    def _create_bet_button(self, text, color, size):
        btn = Button(
            text=text,
            size_hint=(None, None),
            size=size,
            background_color=(0, 0, 0, 0),
            bold=True,
            font_size="24sp",
        )
        with btn.canvas.before:
            Color(*color)
            btn.bg_rect = RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    12,
                ],
            )

        def update_bg(instance, value):
            btn.bg_rect.pos = instance.pos
            btn.bg_rect.size = instance.size

        btn.bind(pos=update_bg, size=update_bg)
        return btn

    def _create_action_button(self, text, color, size):
        btn = Button(
            text=text,
            size_hint=(None, None),
            size=size,
            background_color=(0, 0, 0, 0),
            bold=True,
            font_size="24sp",
        )
        with btn.canvas.before:
            Color(*color)
            btn.bg_rect = RoundedRectangle(
                pos=btn.pos,
                size=btn.size,
                radius=[
                    15,
                ],
            )

        def update_bg(instance, value):
            btn.bg_rect.pos = instance.pos
            btn.bg_rect.size = instance.size

        btn.bind(pos=update_bg, size=update_bg)
        return btn

    def update_button_states(self):
        is_flying = self.state.state == GameState.FLYING

        try:
            bet_amount = int(self.bet_input.text)
            valid_bet = (
                bet_amount >= Config.MIN_BET and bet_amount <= self.state.balance
            )
        except:
            valid_bet = False

        can_bet = self.state.state == GameState.BETTING and valid_bet
        no_balance = self.state.balance < Config.MIN_BET

        self.place_bet_btn.disabled = not can_bet or is_flying
        self.cash_out_btn.disabled = not is_flying
        self.bet_input.disabled = is_flying or no_balance

        if not valid_bet and not is_flying and not no_balance:
            self.bet_input.background_color = (1, 0.8, 0.8, 1)
        else:
            self.bet_input.background_color = (1, 1, 1, 1)

        for child in self.children:
            if isinstance(child, Button):
                btn_text = child.text
                if btn_text in ["+", "-"] or btn_text in [
                    str(p) for p in Config.BET_PRESETS
                ]:
                    child.disabled = is_flying or no_balance
                elif btn_text == "BACK":
                    child.disabled = is_flying or no_balance
                elif "RESET" in btn_text:
                    child.disabled = is_flying

    def create_history(self):
        history_title = Label(
            text="History",
            font_size="18sp",
            color=(1, 0.2, 0.8, 1),
            bold=True,
            size_hint=(None, None),
            size=(70, 25),
        )
        history_title.pos = (35, self.height - 200)
        self.bind(
            size=lambda *args: setattr(history_title, "pos", (35, self.height - 200))
        )
        self.add_widget(history_title)

        history_container = AnchorLayout(
            size_hint=(None, None), size=(65, 450), anchor_y="top"
        )
        self.history_display = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            size_hint_x=None,
            width=65,
            height=10,
            spacing=8,
        )
        history_container.add_widget(self.history_display)

        history_container.pos = (30, self.height - 660)
        self.bind(
            size=lambda *args: setattr(
                history_container, "pos", (30, self.height - 660)
            )
        )

        self.add_widget(history_container)

    def update_game(self, dt: float):
        if self.state.state == GameState.FLYING:
            self.state.update_multiplier()
            self.engine.update_plane_position()
            self.plane_image.pos = (
                self.engine.plane_x - dp(40),
                self.engine.plane_y - dp(40),
            )
            self.plane_image.center = (self.engine.plane_x, self.engine.plane_y)

            self.multiplier_label.text = f"{self.state.multiplier:.2f}x"
            color = self.engine.get_multiplier_color()
            self.multiplier_label.color = color

            self.potential_label.text = (
                f"Potential: ${self.state.current_bet * self.state.multiplier:.2f}"
            )

            if random.random() < 0.5:
                self.particles.emit(
                    self.engine.plane_x,
                    self.engine.plane_y - 75,
                    75,
                    (1, 0.5, 0.2, 0.9),
                    (0.6, 1.2),
                    (6, 12),
                    (-0.5, 0.5),
                )

            if self.state.check_crash():
                self.trigger_crash()

        self.particles.update(dt)

    def adjust_bet(self, amount: int):
        if self.state.state != GameState.BETTING:
            return
        try:
            current = int(self.bet_input.text)
            new_bet = max(Config.MIN_BET, current + amount)
            self.bet_input.text = str(new_bet)
        except:
            self.bet_input.text = str(Config.MIN_BET)
        self.update_button_states()

    def set_bet(self, amount: int):
        if self.state.state == GameState.BETTING:
            self.bet_input.text = str(max(Config.MIN_BET, amount))
        self.update_button_states()

    def place_bet(self, instance):
        try:
            amount = int(self.bet_input.text)
        except:
            self.bet_input.text = str(Config.MIN_BET)
            return

        if not self.state.can_place_bet(amount):
            return

        self.state.place_bet(amount)
        self.update_button_states()
        self.assets.play_sound("bet")
        self.balance_label.text = f"Balance: ${self.state.balance:.2f}"

        self.engine.generate_flight_path(self.width, self.height)
        self.engine.reset_plane()

        self.place_bet_btn.disabled = True
        self.cash_out_btn.disabled = False
        self.bet_input.disabled = True

        self.particles.emit(
            self.engine.plane_x,
            self.engine.plane_y - 60,
            200,
            (0.5, 0.5, 0.5, 0.5),
            (1.2, 2.5),
            (12, 24),
            (-1.6, 0.8),
        )

        Clock.schedule_once(lambda dt: setattr(self.state, "cooldown_bet", False), 0.5)

    def cash_out(self, instance):
        if not self.state.can_cash_out():
            return

        winnings = self.state.cash_out()
        self.assets.play_sound("cashout")
        self.balance_label.text = f"Balance: ${self.state.balance:.2f}"

        self.show_cash_out_success(winnings)
        self.update_button_states()
        self.update_history_display()

        Clock.schedule_once(
            lambda dt: setattr(self.state, "cooldown_cashout", False), 0.5
        )
        Clock.schedule_once(self.reset_game, 1.0)

    def trigger_crash(self):
        self.assets.play_sound("crash")
        self.update_button_states()
        self.crash_label.text = f"CRASHED AT {self.state.multiplier:.2f}x!"
        Animation(opacity=1, duration=1.0).start(self.crash_label)

        explosion_x = self.engine.plane_x
        explosion_y = self.engine.plane_y
        self.particles.emit(
            explosion_x,
            explosion_y,
            400,
            (1, 0.3, 0.1, 0.8),
            (0.8, 3.0),
            (5, 23),
            (-4, 4),
        )
        Clock.schedule_once(
            lambda dt: self.particles.emit(
                explosion_x,
                explosion_y,
                200,
                (1, 0.4, 0.1, 0.7),
                (0.5, 2.0),
                (8, 18),
                (-5, 5),
            ),
            0.1,
        )
        Animation(opacity=0, duration=0.3).start(self.plane_image)

        self.update_history_display()
        Clock.schedule_once(self.reset_game, 1.5)

    def show_cash_out_success(self, amount: int):
        success_label = Label(
            text=f"+${amount}",
            font_size="36sp",
            bold=True,
            color=(0.2, 1, 0.2, 1),
            size_hint=(None, None),
            size=(150, 50),
            opacity=0,
        )
        success_label.center = (self.engine.plane_x, self.engine.plane_y + 100)
        self.add_widget(success_label)

        anim = (
            Animation(opacity=1, duration=0.2)
            + Animation(pos=(success_label.x, success_label.y + dp(100)), duration=0.8)
            + Animation(opacity=0, duration=0.2)
        )
        anim.bind(on_complete=lambda *args: self.remove_widget(success_label))
        anim.start(success_label)

    def update_history_display(self):
        self.history_display.clear_widgets()
        history_list = list(self.state.history)
        self.history_display.height = len(history_list) * 53
        for result in history_list:
            mult = result["multiplier"]

            result_label = Label(
                text=f"{mult:.2f}x",
                font_size="16sp",
                bold=True,
                color=(1, 0.6, 0.8, 1),
                size_hint=(1, None),
                height=45,
            )
            self.history_display.add_widget(result_label)

    def reset_game(self, dt):
        self.state.reset_to_betting()
        self.engine.reset_plane()
        self.plane_image.pos = (Config.PLANE_START_X - 40, Config.PLANE_START_Y - 40)
        self.plane_image.center = (Config.PLANE_START_X, Config.PLANE_START_Y)
        self.plane_image.center = (Config.PLANE_START_X, Config.PLANE_START_Y)
        self.plane_image.opacity = 1

        self.place_bet_btn.disabled = False
        self.cash_out_btn.disabled = True
        self.bet_input.disabled = False

        self.multiplier_label.text = "1.00x"
        self.multiplier_label.color = (1, 1, 1, 0.9)
        Animation(opacity=0, duration=0.5).start(self.crash_label)
        self.potential_label.text = "Potential: $0.00"
        self.update_button_states()

    def reset_balance(self, instance):
        if self.state.state == GameState.BETTING:
            self.state.reset_balance()
            self.balance_label.text = f"Balance: ${self.state.balance:.2f}"
            self.update_button_states()
            self.update_history_display()

    def go_back(self, instance):
        if self.state.state == GameState.BETTING:
            self.parent.manager.transition = SlideTransition(direction="right")
            self.parent.manager.current = "start"


class shiiiuuuu(App):
    def build(self):
        self.title = "Shiiiuuuu"
        sm = ScreenManager(transition=FadeTransition())

        start_screen = StartScreen(name="start")
        game_screen = GameScreen(name="game")
        stats_screen = StatsScreen(game_screen.state_manager, name="stats")
        credits_screen = CreditsScreen(name="credits")

        sm.add_widget(start_screen)
        sm.add_widget(game_screen)
        sm.add_widget(stats_screen)
        sm.add_widget(credits_screen)

        return sm


if __name__ == "__main__":
    shiiiuuuu().run()

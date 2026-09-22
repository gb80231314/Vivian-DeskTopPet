import logging
import math
import random
import time
from typing import Optional, Callable

from .config import ANIMATION_STATES

logger = logging.getLogger(__name__)

BEHAVIOR_PRESETS = {
    "playful": {
        "name": "调皮模式",
        "description": "频繁跑动、跳跃、挥手",
        "anim_weights": {
            "idle": 15,
            "running-right": 25,
            "running-left": 25,
            "waving": 15,
            "jumping": 20,
            "failed": 0,
            "waiting": 0,
            "running": 0,
            "review": 0,
        },
        "move_probability": 0.4,
        "jump_probability": 0.15,
        "interaction_interval": (5, 20),
    },
    "relaxed": {
        "name": "悠闲模式",
        "description": "主要是待机，偶尔挥手看看",
        "anim_weights": {
            "idle": 50,
            "running-right": 5,
            "running-left": 5,
            "waving": 15,
            "jumping": 5,
            "failed": 0,
            "waiting": 10,
            "running": 5,
            "review": 5,
        },
        "move_probability": 0.1,
        "jump_probability": 0.03,
        "interaction_interval": (15, 60),
    },
    "curious": {
        "name": "好奇模式",
        "description": "到处探索，看向各个方向",
        "anim_weights": {
            "idle": 10,
            "running-right": 30,
            "running-left": 30,
            "waving": 10,
            "jumping": 10,
            "failed": 0,
            "waiting": 5,
            "running": 5,
            "review": 0,
        },
        "move_probability": 0.6,
        "jump_probability": 0.1,
        "interaction_interval": (3, 12),
    },
    "active": {
        "name": "活跃模式",
        "description": "忙碌工作、审阅、不断活动",
        "anim_weights": {
            "idle": 5,
            "running-right": 15,
            "running-left": 15,
            "waving": 10,
            "jumping": 10,
            "failed": 5,
            "waiting": 5,
            "running": 20,
            "review": 15,
        },
        "move_probability": 0.35,
        "jump_probability": 0.12,
        "interaction_interval": (3, 10),
    },
}

class RandomBehaviorEngine:

    def __init__(self,
                 preset: str = "playful",
                 screen_width: int = 1920,
                 screen_height: int = 1080,
                 pet_width: int = 192,
                 pet_height: int = 208,
                 on_anim_change: Optional[Callable] = None,
                 on_move: Optional[Callable] = None):
        self.set_preset(preset)
        self.screen_w = screen_width
        self.screen_h = screen_height
        self.pet_w = pet_width
        self.pet_h = pet_height

        self.on_anim_change = on_anim_change
        self.on_move = on_move

        self.current_anim = "idle"
        self.current_x = screen_width // 2
        self.current_y = screen_height // 2
        self.target_x = self.current_x
        self.target_y = self.current_y

        self._last_action_time = time.time()
        self._next_action_time = 0
        self._last_move_time = time.time()
        self._move_target_time = 0
        self._schedule_next_action()

        self._anim_elapsed = 0
        self._anim_duration = 3.0

        self._walking = False
        self._walk_start = (self.current_x, self.current_y)
        self._walk_target = (self.current_x, self.current_y)
        self._walk_duration = 0
        self._walk_elapsed = 0

        self._wander_path: list[tuple[int, int]] = []
        self._wander_index = 0

        self.enabled = False

    def set_preset(self, preset: str):
        if preset not in BEHAVIOR_PRESETS:
            logger.warning(f"未知行为预设 '{preset}'，使用 'playful'")
            preset = "playful"
        self.preset_name = preset
        self.preset = BEHAVIOR_PRESETS[preset]
        logger.info(f"行为预设切换为: {self.preset['name']}")

    def _schedule_next_action(self):
        low, high = self.preset["interaction_interval"]
        interval = random.uniform(low, high)
        self._next_action_time = time.time() + interval

    def update(self, dt: float = 1.0):
        if not self.enabled:
            return

        now = time.time()

        if self._walking:
            self._walk_elapsed += dt
            progress = min(self._walk_elapsed / self._walk_duration, 1.0)

            from .animation_engine import interpolate
            t = interpolate(0, 1, progress, "ease_out")

            sx, sy = self._walk_start
            tx, ty = self._walk_target
            self.current_x = sx + (tx - sx) * t
            self.current_y = sy + (ty - sy) * t

            if self.on_move:
                self.on_move(int(self.current_x), int(self.current_y))

            if progress >= 1.0:
                self._walking = False

                self._switch_anim("idle")
                self._schedule_next_action()

        if now >= self._next_action_time and not self._walking:
            self._perform_random_action()
            self._schedule_next_action()

        self._anim_elapsed += dt
        if self._anim_elapsed >= self._anim_duration and not self._walking:
            self._switch_anim("idle")

    def _perform_random_action(self):
        action = random.random()

        if action < self.preset["move_probability"]:
            self._random_move()

        elif action < self.preset["move_probability"] + self.preset["jump_probability"]:
            self._random_jump()

        else:
            self._random_anim()

    def _random_anim(self):
        weights = self.preset["anim_weights"]
        anims = list(weights.keys())
        w = [weights[a] for a in anims]

        chosen = random.choices(anims, weights=w, k=1)[0]
        self._switch_anim(chosen)

    def _random_move(self):

        margin = 50
        tx = random.randint(margin, self.screen_w - self.pet_w - margin)
        ty = random.randint(margin, self.screen_h - self.pet_h - margin - 40)

        self._start_walk(tx, ty)

    def _random_jump(self):
        self._switch_anim("jumping")
        self._anim_duration = 2.0
        self._anim_elapsed = 0

    def _start_walk(self, tx: int, ty: int):
        dx = tx - self.current_x
        dy = ty - self.current_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < 20:
            return

        if abs(dx) > abs(dy):
            self._switch_anim("running-right" if dx > 0 else "running-left")
        else:
            self._switch_anim("running-right" if dx > 0 else "running-left")

        speed = 200.0
        self._walk_start = (self.current_x, self.current_y)
        self._walk_target = (tx, ty)
        self._walk_duration = max(dist / speed, 0.5)
        self._walk_elapsed = 0
        self._walking = True

    def _switch_anim(self, anim_name: str):
        if anim_name == self.current_anim:
            return

        self.current_anim = anim_name
        self._anim_elapsed = 0
        self._anim_duration = random.uniform(1.5, 5.0)

        if self.on_anim_change:
            self.on_anim_change(anim_name)

    def generate_wander_path(self, segments: int = 5):
        margin = 50
        path = [(self.current_x, self.current_y)]

        for _ in range(segments):
            tx = random.randint(margin, self.screen_w - self.pet_w - margin)
            ty = random.randint(margin, self.screen_h - self.pet_h - margin - 40)
            path.append((tx, ty))

        self._wander_path = path
        self._wander_index = 1

    def wander_next(self):
        if self._wander_index >= len(self._wander_path):
            return

        tx, ty = self._wander_path[self._wander_index]
        self._start_walk(tx, ty)
        self._wander_index += 1

    def get_next_action_hint(self) -> Optional[dict]:
        if not self.enabled:
            return None

        remaining = max(0, self._next_action_time - time.time())
        return {
            "next_in": round(remaining, 1),
            "current_anim": self.current_anim,
            "walking": self._walking,
            "preset": self.preset["name"],
        }

    def stop(self):
        self.enabled = False
        self._walking = False

class RandomEffectTrigger:

    def __init__(self):
        self.cooldowns: dict[str, float] = {}
        self.last_effect_time: dict[str, float] = {}

    def can_trigger(self, effect_name: str, cooldown: float = 5.0) -> bool:
        now = time.time()
        last = self.last_effect_time.get(effect_name, 0)
        return (now - last) >= cooldown

    def trigger(self, effect_name: str):
        self.last_effect_time[effect_name] = time.time()

    def random_effect(self, x: int, y: int) -> Optional[str]:
        effects = ["sparkle", "heart", "bounce", None]
        weights = [0.15, 0.1, 0.1, 0.65]

        chosen = random.choices(effects, weights=weights, k=1)[0]

        if chosen and self.can_trigger(chosen, cooldown=8.0):
            self.trigger(chosen)
            return chosen

        return None

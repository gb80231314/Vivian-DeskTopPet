import math
import random
from typing import Callable, Optional

try:
    import tkinter as tk
except ImportError:
    tk = None

def ease_linear(t: float) -> float:
    return t

def ease_in_quad(t: float) -> float:
    return t * t

def ease_out_quad(t: float) -> float:
    return t * (2 - t)

def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return -1 + (4 - 2 * t) * t

def ease_in_cubic(t: float) -> float:
    return t * t * t

def ease_out_cubic(t: float) -> float:
    t -= 1
    return t * t * t + 1

def ease_in_out_cubic(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    t -= 1
    return 4 * t * t * t + 1

def ease_in_elastic(t: float) -> float:
    if t == 0 or t == 1:
        return t
    return -(2 ** (10 * (t - 1))) * math.sin((t - 1.1) * 5 * math.pi / 1.2)

def ease_out_elastic(t: float) -> float:
    if t == 0 or t == 1:
        return t
    return 2 ** (-10 * t) * math.sin((t - 0.1) * 5 * math.pi / 1.2) + 1

def ease_in_out_elastic(t: float) -> float:
    if t == 0 or t == 1:
        return t
    t *= 2
    if t < 1:
        return -0.5 * (2 ** (10 * (t - 1))) * math.sin((t - 1.1) * 5 * math.pi / 1.1)
    t -= 1
    return 0.5 * (2 ** (-10 * t)) * math.sin((t - 0.1) * 5 * math.pi / 1.1) + 1

def ease_out_bounce(t: float) -> float:
    if t < 1 / 2.75:
        return 7.5625 * t * t
    elif t < 2 / 2.75:
        t -= 1.5 / 2.75
        return 7.5625 * t * t + 0.75
    elif t < 2.5 / 2.75:
        t -= 2.25 / 2.75
        return 7.5625 * t * t + 0.9375
    else:
        t -= 2.625 / 2.75
        return 7.5625 * t * t + 0.984375

def ease_out_back(t: float) -> float:
    s = 1.70158
    t -= 1
    return t * t * ((s + 1) * t + s) + 1

EASING_FUNCTIONS = {
    "linear":       ease_linear,
    "ease_in":      ease_in_quad,
    "ease_out":     ease_out_quad,
    "ease_in_out":  ease_in_out_quad,
    "ease_in_cubic":     ease_in_cubic,
    "ease_out_cubic":    ease_out_cubic,
    "ease_in_out_cubic": ease_in_out_cubic,
    "elastic_out":  ease_out_elastic,
    "elastic_in_out": ease_in_out_elastic,
    "bounce_out":   ease_out_bounce,
    "back_out":     ease_out_back,
}

def interpolate(from_val: float, to_val: float, t: float,
                easing: str = "ease_out") -> float:
    fn = EASING_FUNCTIONS.get(easing, ease_out_quad)
    return from_val + (to_val - from_val) * fn(min(max(t, 0), 1))

class TransitionAnimator:

    def __init__(self):
        self._transitions: dict = {}
        self._current_state: str = "idle"

    def start_transition(self, from_state: str, to_state: str,
                         duration_ms: int = 300, easing: str = "ease_out"):
        import time
        key = (from_state, to_state)
        self._transitions[key] = {
            "start_time": time.time() * 1000,
            "duration": duration_ms,
            "easing": easing,
            "active": True,
        }
        return key

    def get_transition_progress(self, from_state: str,
                                to_state: str) -> Optional[float]:
        import time
        key = (from_state, to_state)
        t = self._transitions.get(key)
        if not t or not t["active"]:
            return None

        elapsed = time.time() * 1000 - t["start_time"]
        if elapsed >= t["duration"]:
            t["active"] = False
            return None

        return min(elapsed / t["duration"], 1.0)

    def get_blend_alpha(self, from_state: str, to_state: str) -> Optional[float]:
        prog = self.get_transition_progress(from_state, to_state)
        if prog is None:
            return None
        fn = EASING_FUNCTIONS.get("ease_in_out", ease_in_out_quad)

        return fn(prog)

class SpringAnimation:

    def __init__(self, stiffness: float = 0.15, damping: float = 0.7):
        self.stiffness = stiffness
        self.damping = damping
        self.velocity = 0.0
        self.current = 0.0
        self.target = 0.0
        self._settled = True

    def set_target(self, target: float):
        self.target = target
        self._settled = False

    def update(self, dt: float = 1.0) -> float:
        if self._settled:
            return self.current

        force = (self.target - self.current) * self.stiffness
        self.velocity = (self.velocity + force) * self.damping
        self.current += self.velocity * dt

        if abs(self.velocity) < 0.01 and abs(self.target - self.current) < 0.1:
            self.current = self.target
            self.velocity = 0
            self._settled = True

        return self.current

    def reset(self, value: float = 0.0):
        self.current = value
        self.target = value
        self.velocity = 0
        self._settled = True

    @property
    def is_settled(self) -> bool:
        return self._settled

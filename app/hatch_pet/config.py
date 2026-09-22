CELL_WIDTH = 192
CELL_HEIGHT = 208
COLS = 8
ROWS = 11
ATLAS_WIDTH = CELL_WIDTH * COLS
ATLAS_HEIGHT = CELL_HEIGHT * ROWS

SPRITE_VERSION_NUMBER = 2
DEFAULT_FPS = 6
DEFAULT_FRAME_COUNT = 8

CODEC_COMPAT = True

ANIMATION_STATES = [
    {"name": "idle",          "row": 0, "label": "待机",     "repeat": True,  "fps": 4},
    {"name": "running-right", "row": 1, "label": "向右跑",    "repeat": True,  "fps": 8},
    {"name": "running-left",  "row": 2, "label": "向左跑",    "repeat": True,  "fps": 8},
    {"name": "waving",        "row": 3, "label": "挥手",     "repeat": True,  "fps": 6},
    {"name": "jumping",       "row": 4, "label": "跳跃",     "repeat": False, "fps": 6},
    {"name": "failed",        "row": 5, "label": "失败",     "repeat": False, "fps": 4},
    {"name": "waiting",       "row": 6, "label": "等待",     "repeat": True,  "fps": 4},
    {"name": "running",       "row": 7, "label": "工作中",    "repeat": True,  "fps": 6},
    {"name": "review",        "row": 8, "label": "审阅",     "repeat": True,  "fps": 6},
]

GAZE_DIRECTIONS = [

    {"name": "gaze-000",     "row": 9,  "col": 0, "angle": 0.0,   "label": "up"},
    {"name": "gaze-022.5",   "row": 9,  "col": 1, "angle": 22.5,  "label": "up-right"},
    {"name": "gaze-045",     "row": 9,  "col": 2, "angle": 45.0,  "label": "up-right"},
    {"name": "gaze-067.5",   "row": 9,  "col": 3, "angle": 67.5,  "label": "up-right"},
    {"name": "gaze-090",     "row": 9,  "col": 4, "angle": 90.0,  "label": "right"},
    {"name": "gaze-112.5",   "row": 9,  "col": 5, "angle": 112.5, "label": "down-right"},
    {"name": "gaze-135",     "row": 9,  "col": 6, "angle": 135.0, "label": "down-right"},
    {"name": "gaze-157.5",   "row": 9,  "col": 7, "angle": 157.5, "label": "down-right"},

    {"name": "gaze-180",     "row": 10, "col": 0, "angle": 180.0, "label": "down"},
    {"name": "gaze-202.5",   "row": 10, "col": 1, "angle": 202.5, "label": "down-left"},
    {"name": "gaze-225",     "row": 10, "col": 2, "angle": 225.0, "label": "down-left"},
    {"name": "gaze-247.5",   "row": 10, "col": 3, "angle": 247.5, "label": "down-left"},
    {"name": "gaze-270",     "row": 10, "col": 4, "angle": 270.0, "label": "left"},
    {"name": "gaze-292.5",   "row": 10, "col": 5, "angle": 292.5, "label": "up-left"},
    {"name": "gaze-315",     "row": 10, "col": 6, "angle": 315.0, "label": "up-left"},
    {"name": "gaze-337.5",   "row": 10, "col": 7, "angle": 337.5, "label": "up-left"},
]

# -*- coding: utf-8 -*-
"""合成 15s 轻柔八音盒风格 BGM（纯 numpy，无外部音频素材）"""
import numpy as np
import wave

SR = 44100
DUR = 15.0
N = int(SR * DUR)
L = np.zeros(N); R = np.zeros(N)

def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)

def music_box(freq, dur=1.4, gain=1.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    y = (np.sin(2*np.pi*freq*t) + 0.35*np.sin(4*np.pi*freq*t)
         + 0.12*np.sin(6*np.pi*freq*t)) * np.exp(-t * 3.2)
    atk = int(SR * 0.004)
    y[:atk] *= np.linspace(0, 1, atk)
    return y * gain

def pad(freq, dur, gain=1.0):
    n = int(SR * dur)
    t = np.arange(n) / SR
    y = np.sin(2*np.pi*freq*t) * 0.6 + np.sin(2*np.pi*freq*2*t) * 0.15
    env = np.minimum(1, t/0.5) * np.minimum(1, (dur-t)/0.8)
    env = np.clip(env, 0, 1)
    return y * env * gain

def add(sig, t0, pan=0.5):
    i0 = int(t0 * SR)
    i1 = min(N, i0 + len(sig))
    if i1 <= i0:
        return
    seg = sig[:i1-i0]
    L[i0:i1] += seg * (1 - pan)
    R[i0:i1] += seg * pan

# 和弦进行 C G Am F ×2，每和弦 1.875s（8 个八分音符琶音）
CHORDS = [
    [60, 64, 67, 72],   # C
    [59, 62, 67, 71],   # G
    [57, 60, 64, 69],   # Am
    [53, 57, 60, 65],   # F
] * 2
CHORD_DUR = 1.875
EIGHTH = CHORD_DUR / 8

note_i = 0
for ci, ch in enumerate(CHORDS):
    t0 = ci * CHORD_DUR
    # 琶音（高八度八音盒音色）
    order = [0, 1, 2, 3, 2, 1, 2, 3]
    for k, oi in enumerate(order):
        f = mtof(ch[oi] + 12)
        add(music_box(f, gain=0.5), t0 + k*EIGHTH, pan=0.35 if k % 2 == 0 else 0.65)
    # 低音 pad（根音低八度）
    root = ch[0] - 12
    for m in {root, root+7}:
        add(pad(mtof(m), CHORD_DUR, gain=0.10), t0, pan=0.5)
    note_i += 1

# 简单旋律点缀（每小节长音）
MELODY = [(0.0, 76, 1.6), (1.875, 79, 1.6), (3.75, 81, 1.6), (5.625, 79, 1.6),
          (7.5, 76, 1.6), (9.375, 81, 1.6), (11.25, 84, 1.6), (13.125, 79, 1.8)]
for t0, m, dur in MELODY:
    add(music_box(mtof(m), dur=dur, gain=0.34), t0, pan=0.5)

# 收尾主和弦
add(music_box(mtof(84), dur=2.0, gain=0.5), 13.4, pan=0.4)
add(music_box(mtof(79), dur=2.0, gain=0.4), 13.4, pan=0.6)

mix = np.stack([L, R], axis=1)
mix = mix / np.max(np.abs(mix)) * 0.55
pcm = (mix * 32767).astype(np.int16)

with wave.open("F:/AiWorkProject/2026-09-17-22-43-10/pet-work/video/bgm.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("BGM_OK 15.0s")

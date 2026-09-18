"""Compatibility for Vector weapon BMP scoring and legacy recoil parameters."""

import math
import random
import time

import cv2
import numpy as np


def gray(bgr):
    return ((bgr[:, :, 0].astype(np.uint16) * 29 + bgr[:, :, 1].astype(np.uint16) * 150 + bgr[:, :, 2].astype(np.uint16) * 77) >> 8).astype(np.uint8)


def resize(image, width=100, height=64):
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)


def _hashes(image):
    a = resize(image, 8, 8).astype(np.float64)
    ah = (a >= a.mean()).ravel()
    d = resize(image, 9, 8)
    dh = (d[:, :-1] > d[:, 1:]).ravel()
    p = resize(image, 32, 32).astype(np.float32)
    coeff = cv2.dct(p)[:8, :8].ravel()
    ph = coeff[1:] >= np.median(coeff[1:])
    return ah, dh, ph


def _corr(a, b):
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a -= a.mean()
    b -= b.mean()
    denominator = math.sqrt(float(a @ a) * float(b @ b))
    return max(0.0, min(1.0, (float(a @ b) / denominator + 1) / 2)) if denominator else 0.0


def _edge(image):
    x = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
    y = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)
    edge = np.minimum(np.sqrt(x * x + y * y).astype(np.int32), 255).astype(np.uint8)
    edge[[0, -1], :] = 0
    edge[:, [0, -1]] = 0
    return edge


def score(capture, template):
    a, b = resize(capture), resize(template)
    hashes_a, hashes_b = _hashes(a), _hashes(b)
    hash_score = sum(1 - np.count_nonzero(x != y) / 64 for x, y in zip(hashes_a, hashes_b)) / 3
    hist_a = np.bincount((a >> 3).ravel(), minlength=32)
    hist_b = np.bincount((b >> 3).ravel(), minlength=32)
    hist_score = _corr(hist_a, hist_b)
    zncc = _corr(a, b)
    fa, fb = a.astype(np.float64), b.astype(np.float64)
    ma, mb = fa.mean(), fb.mean()
    va, vb = fa.var(ddof=1), fb.var(ddof=1)
    covariance = float(((fa - ma) * (fb - mb)).sum()) / (fa.size - 1)
    ssim = (2 * ma * mb + 6.5025) * (2 * covariance + 58.5225) / ((ma * ma + mb * mb + 6.5025) * (va + vb + 58.5225))
    return max(0.0, min(1.0, hash_score * .26 + hist_score * .16 + zncc * .24 + ssim * .22 + _corr(_edge(a), _edge(b)) * .12))


DIRECTIONS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1),
              "down_left": (-.5, .5), "down_right": (.5, .5), "up_left": (-.5, -.5), "up_right": (.5, -.5)}


def legacy_step(weapon, elapsed, dt, impulse_index, impulse_due, scale, rng):
    x = y = 0.0
    if impulse_due:
        level = min(200, max(-200, math.trunc(float(weapon.get("level", 0)) * scale / 3) + 1))
        pulse = level if impulse_index % 2 == 0 else -level
        x += pulse + rng.gauss(0, .2)
        y += pulse + rng.gauss(0, .2)
    decline = float(weapon.get("decline", 0)) + (float(weapon.get("initial_drop", 0)) if elapsed < .15 else 0)
    y += (.92 + rng.random() * .16) * decline * scale * dt
    for part in weapon.get("adjustments") or []:
        if part.get("enabled", True) and float(part.get("start_time", 0)) <= elapsed < float(part.get("start_time", 0)) + float(part.get("duration", 0)):
            direction = DIRECTIONS.get(part.get("direction"), (0, 0))
            amount = float(part.get("intensity", 0)) * dt * scale
            x += direction[0] * amount
            y += direction[1] * amount
    return x, y


def play(mouse, weapon, settings, stop_event, buttons_down):
    rng = random.Random()
    start = last = next_impulse = time.perf_counter()
    impulse = 0
    residual_x = residual_y = 0.0
    frequency = float(weapon.get("frequency") or 10)
    if frequency <= 0:
        frequency = 10
    scale = float(settings.get("scale", 1)) * float(settings.get("sensitivity", 1)) * float(weapon.get("power", 100)) / 100
    tick = max(.002, float(settings.get("tick_ms", 10)) / 1000)
    while not stop_event.is_set() and buttons_down():
        now = time.perf_counter()
        elapsed = now - start
        if elapsed < float(weapon.get("start_delay", 0)):
            stop_event.wait(min(tick, .01))
            continue
        dt = now - last
        if dt < .002:
            stop_event.wait(.002 - dt)
            continue
        due = now >= next_impulse
        x, y = legacy_step(weapon, elapsed, dt, impulse, due, scale, rng)
        if due:
            impulse += 1
            next_impulse = now + max(.5, rng.gauss(1, .04)) / frequency
        residual_x += x * float(weapon.get("x_power", 100)) / 100
        residual_y += y * float(weapon.get("y_power", 100)) / 100
        dx, dy = max(-200, min(200, math.trunc(residual_x))), max(-200, min(200, math.trunc(residual_y)))
        residual_x -= dx
        residual_y -= dy
        if dx or dy:
            mouse.move_relative(dx, dy)
        last = now
        stop_event.wait(tick)

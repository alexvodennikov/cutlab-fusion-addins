# -*- coding: utf-8 -*-
"""Расчётное ядро генератора коробов на Lamello Cabineo. Чистый Python.

Короб из пяти панелей (верх, низ, две боковины, врезной задник заподлицо).
Соединение углов:
  joint='straight' — прямые детали, крепёж Cabineo 8;
      схема 'A' — верх и низ во всю ширину, боковины между ними;
      схема 'B' — боковины во всю высоту, верх и низ между ними;
  joint='tabs' — взаимная гребёнка как в CabinetGenerator (обе панели
      полные, чередующиеся пальцы по глубине, пилоты Ø3 под шурупы сквозь
      пальцы горизонтов); Cabineo на угловые швы при этом не ставится.

Фрезеровка Cabineo 8 — из официального листа Lamello (Cabineo 02/24,
Art.No. 986320VS, файл Lamello_Cabineo_machining.pdf), вариант
«Bund aufliegend» (шляпка на поверхности), фреза >=Ø10:
  - карман: три окружности Ø15, глубина 11.0, центры на 3.6 / 14.8 / 26.0 мм
    от кромки примыкания (первая окружность открыта в торец);
  - пилот в ответной детали: Ø5, глубина X = 8, ось на 5 мм от карманной
    пласти примыкающей детали;
  - панель с карманом >=12 мм, с пилотом >=16 мм; шаг <=300, от угла >=20.
Реконструкция из клиентского файла (20.4×13.2) не используется — дважды
бракована сборщиком.

cab_face: 'outside' — шляпки на наружных пластях (скрытый изнутри крепёж),
'inside' — шляпки внутрь короба (когда наружные пласти на виду).

Система координат: X — ширина, Y — глубина (перёд = 0), Z — высота. Мм.
"""

from dataclasses import dataclass, field
import math

# ----- Cabineo 8, Bund aufliegend, Fräser >=Ø10 (официальный лист) -----
CAB_CUP_D = 15.0                 # диаметр окружностей кармана
CAB_CUP_CENTERS = (3.6, 14.8, 26.0)   # центры от кромки примыкания
CAB_POCKET_DEPTH = 11.0          # глубина кармана от пласти
CAB_PILOT_D = 5.0                # пилот в ответной детали
CAB_PILOT_DEPTH = 8.0              # X = 8 мм для Cabineo 8: глубина пилота от плоскости стыка (лист Lamello 02/24)
CAB_AXIS_X = 5.0                 # ось винта в 5 мм от карманной пласти (лист: 5 / D-5); до 01.10.2026 было 8 — ошибка, X это глубина
CAB_MIN_EDGE = 20.0
CAB_MAX_STEP = 300.0
CAB_MIN_T_POCKET = 12.0
CAB_MIN_T_PILOT = 16.0


@dataclass
class BoxParams:
    width: float = 800.0          # наружные габариты
    height: float = 426.0
    depth: float = 748.0
    material_t: float = 18.0

    joint: str = "straight"       # 'straight' | 'tabs'
    scheme: str = "A"             # для straight: 'A' | 'B'
    n_tabs: int = 3               # для tabs: шипов горизонта на угол
    tab_clearance: float = 0.1    # зазор посадки гребёнки на сторону
    tab_pilot_d: float = 3.0      # пилот под шуруп сквозь пальцы горизонтов

    # Cabineo
    cab_sides: bool = True        # Cabineo на угловых швах (только straight)
    cab_back: bool = True         # Cabineo на швах задника
    cab_face: str = "outside"     # 'outside' | 'inside' — куда шляпки
    cab_edge: float = 50.0        # отступ крайних коннекторов от концов шва
    cab_step: float = 250.0       # шаг для авто-количества
    cab_count_side: int = 0       # коннекторов на угловой шов (0 = авто)
    cab_count_back: int = 0       # на каждый шов задника (0 = авто)

    # съёмный задник (вместо Cabineo задника)
    removable_back: bool = False
    stop_len: float = 100.0       # упор: длина вдоль шва
    stop_w: float = 60.0          # упор: ширина (t на торце + свес в проём)
    magnet_d: float = 18.0
    magnet_t: float = 5.0
    magnet_fit: float = 0.3
    stop_screw_d: float = 4.0     # сквозной пилот в упоре

    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0


@dataclass
class Part:
    name: str
    plane: str                    # 'xy' | 'yz' | 'xz'
    c0: float
    th: float
    rect: tuple                   # (u0, v0, u1, v1)
    cuts: list = field(default_factory=list)      # сквозные прямоугольники
    holes: list = field(default_factory=list)     # сквозные (u, v, d)
    pockets: list = field(default_factory=list)   # (face, depth, [(u,v,d)..])
    #   face: 'c0' — с пласти c0, 'far' — с пласти c0+th
    edge_front: float = 0.0


def segments(length, n):
    """2n+1 сегментов: чётные (вкл. края) — 'A', нечётные — 'B'."""
    k = 2 * n + 1
    w = length / k
    return [(i * w, (i + 1) * w, "A" if i % 2 == 0 else "B")
            for i in range(k)]


def _positions(length, edge, step, count):
    lo, hi = edge, length - edge
    if hi <= lo:
        return [length / 2.0]
    n = count if count and count > 0 else \
        max(2, int(math.ceil((hi - lo) / step)) + 1)
    if n == 1:
        return [(lo + hi) / 2.0]
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def _pk_v(u_along, v_edge, direction):
    """Карман, открытый к горизонтальной кромке (уходит по v)."""
    return [(u_along, v_edge + direction * c, CAB_CUP_D)
            for c in CAB_CUP_CENTERS]


def _pk_u(u_edge, v_along, direction):
    """Карман, открытый к вертикальной кромке (уходит по u)."""
    return [(u_edge + direction * c, v_along, CAB_CUP_D)
            for c in CAB_CUP_CENTERS]


def compute(p: BoxParams):
    W, H, D, t = p.width, p.height, p.depth, p.material_t
    warnings = []
    if t < CAB_MIN_T_POCKET:
        warnings.append(f"Плита {t:.0f} < 12 — Cabineo 8 не встанет")
    elif t < CAB_MIN_T_PILOT and (p.cab_sides or p.cab_back):
        warnings.append(f"Плита {t:.0f} < 16 — сторона с пилотом вне "
                        f"спецификации Lamello")
    if p.joint not in ("straight", "tabs"):
        raise ValueError("joint: 'straight' | 'tabs'")
    if p.scheme not in ("A", "B"):
        raise ValueError("scheme: 'A' | 'B'")

    outside = (p.cab_face == "outside")
    pos_side = _positions(D, p.cab_edge, p.cab_step, p.cab_count_side)
    pos_back_w = _positions(W - 2 * t, p.cab_edge, p.cab_step,
                            p.cab_count_back)
    pos_back_h = _positions(H - 2 * t, p.cab_edge, p.cab_step,
                            p.cab_count_back)

    n_cab = 0
    parts = []

    # ---------------- панели и угловые швы ----------------
    if p.joint == "tabs":
        # обе панели полные, взаимная гребёнка по глубине (как CabinetGen)
        c = p.tab_clearance
        segY = segments(D, p.n_tabs)
        niz = Part("Низ", "xy", 0.0, t, (0.0, 0.0, W, D),
                   edge_front=W - 2 * t)
        verh = Part("Верх", "xy", H - t, t, (0.0, 0.0, W, D),
                    edge_front=W - 2 * t)
        bok_l = Part("Бок Л", "yz", 0.0, t, (0.0, 0.0, D, H), edge_front=H)
        bok_r = Part("Бок П", "yz", W - t, t, (0.0, 0.0, D, H), edge_front=H)
        for a, b, kind in segY:
            if kind == "A":       # пальцы боковины -> вырезы в горизонтах
                for hor in (niz, verh):
                    hor.cuts.append((0.0, a - c, t + c, b + c))
                    hor.cuts.append((W - t - c, a - c, W, b + c))
            else:                 # пальцы горизонтов -> вырезы в боковинах
                for bok in (bok_l, bok_r):
                    bok.cuts.append((a - c, 0.0, b + c, t + c))
                    bok.cuts.append((a - c, H - t - c, b + c, H))
                # пилоты Ø3 сквозь пальцы горизонтов (шуруп в тело боковины)
                mid = (a + b) / 2.0
                for u in (t / 2.0, W - t / 2.0):
                    niz.holes.append((u, mid, p.tab_pilot_d))
                    verh.holes.append((u, mid, p.tab_pilot_d))
        if p.cab_sides:
            warnings.append("Гребёнка: Cabineo на угловые швы не ставится")
    else:
        if p.scheme == "A":
            niz = Part("Низ", "xy", 0.0, t, (0.0, 0.0, W, D), edge_front=W)
            verh = Part("Верх", "xy", H - t, t, (0.0, 0.0, W, D),
                        edge_front=W)
            bok_l = Part("Бок Л", "yz", 0.0, t, (0.0, t, D, H - t),
                         edge_front=H - 2 * t)
            bok_r = Part("Бок П", "yz", W - t, t, (0.0, t, D, H - t),
                         edge_front=H - 2 * t)
        else:
            bok_l = Part("Бок Л", "yz", 0.0, t, (0.0, 0.0, D, H),
                         edge_front=H)
            bok_r = Part("Бок П", "yz", W - t, t, (0.0, 0.0, D, H),
                         edge_front=H)
            niz = Part("Низ", "xy", 0.0, t, (t, 0.0, W - t, D),
                       edge_front=W - 2 * t)
            verh = Part("Верх", "xy", H - t, t, (t, 0.0, W - t, D),
                        edge_front=W - 2 * t)

        if p.cab_sides:
            if p.scheme == "A":
                # карманы в боковинах, пилоты в горизонтах.
                # outside: карманная пласть = наружная (Л: c0, П: far);
                # inside: внутренняя (Л: far, П: c0)
                f_l = "c0" if outside else "far"
                f_r = "far" if outside else "c0"
                ax_l = CAB_AXIS_X if outside else t - CAB_AXIS_X
                ax_r = W - CAB_AXIS_X if outside else W - t + CAB_AXIS_X
                for pos in pos_side:
                    for v_edge, direc in ((t, +1), (H - t, -1)):
                        bok_l.pockets.append(
                            (f_l, CAB_POCKET_DEPTH, _pk_v(pos, v_edge, direc)))
                        bok_r.pockets.append(
                            (f_r, CAB_POCKET_DEPTH, _pk_v(pos, v_edge, direc)))
                    for u in (ax_l, ax_r):
                        niz.pockets.append(("far", CAB_PILOT_DEPTH,
                                            [(u, pos, CAB_PILOT_D)]))
                        verh.pockets.append(("c0", CAB_PILOT_DEPTH,
                                             [(u, pos, CAB_PILOT_D)]))
                    n_cab += 4
            else:
                # карманы в горизонтах, пилоты в боковинах
                f_n = "c0" if outside else "far"   # низ: наружная пласть снизу
                f_v = "far" if outside else "c0"
                ax_n = CAB_AXIS_X if outside else t - CAB_AXIS_X
                ax_v = H - CAB_AXIS_X if outside else H - t + CAB_AXIS_X
                for pos in pos_side:
                    for u_edge, direc in ((t, +1), (W - t, -1)):
                        niz.pockets.append(
                            (f_n, CAB_POCKET_DEPTH, _pk_u(u_edge, pos, direc)))
                        verh.pockets.append(
                            (f_v, CAB_POCKET_DEPTH, _pk_u(u_edge, pos, direc)))
                    for v, fl, fr in ((ax_n, "far", "c0"),
                                      (ax_v, "far", "c0")):
                        bok_l.pockets.append((fl, CAB_PILOT_DEPTH,
                                              [(pos, v, CAB_PILOT_D)]))
                        bok_r.pockets.append((fr, CAB_PILOT_DEPTH,
                                              [(pos, v, CAB_PILOT_D)]))
                    n_cab += 4

    zad = Part("Задник", "xz", D - t, t, (t, t, W - t, H - t))

    # ---------------- задник ----------------
    if not p.removable_back and p.cab_back:
        # outside: карманы на задней пласти задника ('far'), ось винта
        # на 8 от неё; inside: на передней ('c0')
        f_z = "far" if outside else "c0"
        y_axis = (D - CAB_AXIS_X) if outside else (D - t + CAB_AXIS_X)
        for pos in pos_back_w:
            u = t + pos
            zad.pockets.append((f_z, CAB_POCKET_DEPTH, _pk_v(u, t, +1)))
            zad.pockets.append((f_z, CAB_POCKET_DEPTH, _pk_v(u, H - t, -1)))
            niz.pockets.append(("far", CAB_PILOT_DEPTH,
                                [(u, y_axis, CAB_PILOT_D)]))
            verh.pockets.append(("c0", CAB_PILOT_DEPTH,
                                 [(u, y_axis, CAB_PILOT_D)]))
            n_cab += 2
        for pos in pos_back_h:
            v = t + pos
            zad.pockets.append((f_z, CAB_POCKET_DEPTH, _pk_u(t, v, +1)))
            zad.pockets.append((f_z, CAB_POCKET_DEPTH, _pk_u(W - t, v, -1)))
            bok_l.pockets.append(("far", CAB_PILOT_DEPTH,
                                  [(y_axis, v, CAB_PILOT_D)]))
            bok_r.pockets.append(("c0", CAB_PILOT_DEPTH,
                                  [(y_axis, v, CAB_PILOT_D)]))
            n_cab += 2

    parts += [niz, verh, bok_l, bok_r, zad]

    # ---------------- съёмный задник: упоры с магнитами ----------------
    n_stops = 0
    if p.removable_back:
        mag_d = p.magnet_d + p.magnet_fit
        mag_dep = p.magnet_t + 0.5
        sl, sw = p.stop_len, p.stop_w
        cx, cz = W / 2.0, H / 2.0
        # упор — пластина sl × sw × t на y D..D+t, приложенная к заднему
        # торцу панели, свисает в проём; гнездо магнита в передней пласти
        # ('c0'), два сквозных пилота напротив торца панели
        stops = [
            ("Упор низ", (cx - sl / 2, 0.0, cx + sl / 2, sw),
             (cx, t + (sw - t) / 2),
             [(cx - sl / 2 + 20, t / 2), (cx + sl / 2 - 20, t / 2)]),
            ("Упор верх", (cx - sl / 2, H - sw, cx + sl / 2, H),
             (cx, H - t - (sw - t) / 2),
             [(cx - sl / 2 + 20, H - t / 2), (cx + sl / 2 - 20, H - t / 2)]),
            ("Упор бок Л", (0.0, cz - sl / 2, sw, cz + sl / 2),
             (t + (sw - t) / 2, cz),
             [(t / 2, cz - sl / 2 + 20), (t / 2, cz + sl / 2 - 20)]),
            ("Упор бок П", (W - sw, cz - sl / 2, W, cz + sl / 2),
             (W - t - (sw - t) / 2, cz),
             [(W - t / 2, cz - sl / 2 + 20), (W - t / 2, cz + sl / 2 - 20)]),
        ]
        for name, rect, mag_uv, screws in stops:
            s = Part(name, "xz", D, t, rect)
            s.pockets.append(("c0", mag_dep, [(mag_uv[0], mag_uv[1], mag_d)]))
            for u, v in screws:
                s.holes.append((u, v, p.stop_screw_d))
            parts.append(s)
            # ответное гнездо в задней пласти задника
            zad.pockets.append(("far", mag_dep,
                                [(mag_uv[0], mag_uv[1], mag_d)]))
        n_stops = 4

    # ---------------- отчёт ----------------
    zad.edge_front = 0.0
    area = sum((pt.rect[2] - pt.rect[0]) * (pt.rect[3] - pt.rect[1])
               for pt in parts) / 1e6
    edge_len = sum(pt.edge_front for pt in parts) / 1000.0

    return dict(parts=parts, warnings=warnings, n_cabineo=n_cab,
                n_stops=n_stops, area_m2=round(area, 3),
                edge_front_m=round(edge_len, 2),
                inner=dict(w=W - 2 * t, h=H - 2 * t, d=D - t),
                pos_side=pos_side, pos_back_w=pos_back_w,
                pos_back_h=pos_back_h)


def cutlist_text(p: BoxParams, res):
    joint = "гребёнка" if p.joint == "tabs" else f"схема {p.scheme}"
    lines = [f"Короб {p.width:.0f}×{p.height:.0f}×{p.depth:.0f}, "
             f"плита {p.material_t:.0f}, {joint}, шляпки "
             + ("наружу" if p.cab_face == "outside" else "внутрь")
             + (", задник съёмный" if p.removable_back else "")]
    for pt in res["parts"]:
        w = pt.rect[2] - pt.rect[0]
        h = pt.rect[3] - pt.rect[1]
        extras = []
        if pt.pockets:
            extras.append(f"гнёзд {len(pt.pockets)}")
        if pt.holes:
            extras.append(f"сквозных {len(pt.holes)}")
        if pt.cuts:
            extras.append(f"вырезов {len(pt.cuts)}")
        lines.append(f"  {pt.name:12s} {w:7.1f} × {h:7.1f} × {pt.th:.0f}"
                     + ("  " + ", ".join(extras) if extras else ""))
    lines.append(f"Cabineo 8: {res['n_cabineo']} шт; кромка передних торцов "
                 f"{res['edge_front_m']:.2f} м; площадь {res['area_m2']:.2f} м²")
    for w in res["warnings"]:
        lines.append("! " + w)
    return "\n".join(lines)

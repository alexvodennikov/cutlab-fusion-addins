# -*- coding: utf-8 -*-
"""Расчётное ядро генератора корпусов. Чистый Python, без Fusion.

Корпус из листового материала (фанера 18 мм по умолчанию) на сквозных
шип-пазах под 3-осевой ЧПУ (dogbones пользователь добавляет потом).

Схема (по концепту пользователя):
- Боковины — полная высота, горизонты (дно/крыша) — полная ширина;
  на углах взаимная гребёнка: сторона делится на 2n+1 сегментов,
  чётные (включая крайние) — пальцы боковины, нечётные — горизонта.
- Задник (тонкий, 9 мм) — на шипах по периметру, задний торец заподлицо.
- Пилоты Ø3 под шурупы: сквозь пальцы ГОРИЗОНТОВ (сверлятся с пласти —
  выполнимо на 3 осях; шуруп тянет горизонт к телу боковины) и сквозь
  пальцы ЗАДНИКА. Через пальцы боковин не сверлим (горизонтальное
  сверление 3-осевому недоступно).
- Зазор посадки: пазы шире номинала на clearance с каждой стороны.

Все размеры в мм. Система координат корпуса: X — ширина, Y — глубина
(перёд = 0), Z — высота.
"""

from dataclasses import dataclass, field


@dataclass
class CabinetParams:
    width: float = 600.0            # наружные габариты
    height: float = 720.0
    depth: float = 500.0
    material_t: float = 18.0        # толщина корпусного материала
    material_global: bool = True    # брать толщину из глобального параметра
    has_back: bool = True
    back_t: float = 9.0             # толщина задника
    n_tabs: int = 3                 # шипов ГОРИЗОНТА на угол
    n_back_tabs: int = 3            # шипов задника ПО ВЫСОТЕ (бок. стороны)
    # по ширине задника шипов всегда 3 (ширина корпусов примерно в одних
    # пределах — решение пользователя), раскладываются пропорционально
    n_back_tabs_w: int = 3
    pilot_d: float = 3.0            # пилот под шуруп
    ease_r: float = 1.0             # заходное скругление углов шипов
    clearance: float = 0.1          # зазор посадки на сторону
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_z: float = 0.0

    # --- полки ---
    n_shelves: int = 0
    shelf_type: str = "fixed"       # 'fixed' (шип-паз) | 'adjustable'
    shelf_types: list = None        # опционально: тип на каждую полку по
                                    # индексу ('fixed'|'adjustable'),
                                    # приоритет над shelf_type
    shelf_z: list = None            # низы полок от низа корпуса (None/пусто =
                                    # равномерно по внутренней высоте)
    shelf_pin_d: float = 5.0        # полкодержатель: диаметр
    shelf_pin_depth: float = 12.0   # глухое отверстие в боковине
    shelf_pin_inset: float = 50.0   # ряды отверстий от переднего/заднего края
    shelf_adjust_steps: int = 0     # съёмные: ±N позиций с шагом 32
    shelf_clearance: float = 1.0    # зазор съёмной полки на сторону


@dataclass
class Part:
    name: str
    plane: str          # 'xy' (горизонты) | 'yz' (боковины) | 'xz' (задник)
    c0: float           # координата нижней пласти по нормали плоскости
    th: float           # толщина (экструзия в +нормаль)
    rect: tuple         # (u0, v0, u1, v1) — полный контур в осях плоскости
    cuts: list = field(default_factory=list)    # [(u0,v0,u1,v1), ...]
    holes: list = field(default_factory=list)   # [(u, v, d), ...] сквозные
    # глухие отверстия [(u, v, d, depth), ...], режутся с внутренней пласти
    blind_holes: list = field(default_factory=list)
    inner_face: str = "top"   # 'top' = пласть c0+th внутренняя | 'base' = c0


def segments(length, n):
    """2n+1 сегментов: чётные индексы (вкл. края) — «A», нечётные — «B»."""
    k = 2 * n + 1
    w = length / k
    return [(i * w, (i + 1) * w, "A" if i % 2 == 0 else "B")
            for i in range(k)]


def compute(p: CabinetParams):
    W, H, D = p.width, p.height, p.depth
    t, tb, c = p.material_t, p.back_t, p.clearance
    warnings = []

    if W < 4 * t or H < 4 * t or D < 4 * t:
        warnings.append("Габарит слишком мал относительно толщины")

    segY = segments(D, p.n_tabs)          # углы бок-гориз (вдоль глубины)
    segW = segments(W, p.n_back_tabs_w)   # задник по ширине: всегда 3
    segH = segments(H, p.n_back_tabs)     # задник по высоте: из диалога

    parts = []

    # --- горизонты (дно z 0..t, крыша z H-t..H), пласть XY ---
    for name, z0 in (("Дно", 0.0), ("Крыша", H - t)):
        cuts = []
        holes = []
        for a, b, kind in segY:
            if kind == "A":                       # пальцы боковины -> вырез
                cuts.append((0.0, a - c, t + c, b + c))
                cuts.append((W - t - c, a - c, W, b + c))
            else:                                 # свой палец -> пилот
                mid = (a + b) / 2.0
                holes.append((t / 2.0, mid, p.pilot_d))
                holes.append((W - t / 2.0, mid, p.pilot_d))
        if p.has_back:
            for a, b, kind in segW:
                if kind == "B":                   # пальцы задника -> паз
                    cuts.append((a - c, D - tb - c, b + c, D))
        parts.append(Part(name, "xy", z0, t, (0.0, 0.0, W, D),
                          cuts, holes))

    # --- боковины: вырезы собираем в списки (полки дополнят) ---
    wall_cuts = []                                # общие для Л и П
    wall_blind = []                               # глухие (полкодержатели)
    for a, b, kind in segY:
        if kind == "B":                           # пальцы горизонта -> вырез
            wall_cuts.append((a - c, 0.0, b + c, t + c))
            wall_cuts.append((a - c, H - t - c, b + c, H))
    if p.has_back:
        for a, b, kind in segH:
            if kind == "B":                       # пальцы задника -> паз
                wall_cuts.append((D - tb - c, a - c, D, b + c))

    # --- полки ---
    ds = D - tb if p.has_back else D              # глубина полки (до задника)
    zs_list = list(p.shelf_z or [])
    n_sh = max(0, int(p.n_shelves))
    if n_sh and not zs_list:
        gap = (H - 2.0 * t - n_sh * t) / (n_sh + 1)
        zs_list = [t + (i + 1) * gap + i * t for i in range(n_sh)]
    zs_list = zs_list[:n_sh] if n_sh else zs_list

    def _clip_seg(a, b, hi):
        return (a, min(b, hi)) if a < hi - 1.0 else None

    shelf_parts = []
    for i, zs in enumerate(zs_list, start=1):
        if zs < t or zs + t > H - t:
            warnings.append(f"Полка {i}: высота {zs:.0f} вне проёма — пропущена")
            continue
        sh_type = p.shelf_type
        if p.shelf_types and i - 1 < len(p.shelf_types):
            sh_type = p.shelf_types[i - 1]
        if sh_type == "fixed":
            cuts = []
            holes = []
            for a, b, kind in segY:
                seg = _clip_seg(a, b, ds)
                if seg is None:
                    continue
                a2, b2 = seg
                if kind == "A":                   # тело боковины -> вырез в полке
                    cuts.append((0.0, a2 - c, t + c, b2 + c))
                    cuts.append((W - t - c, a2 - c, W, b2 + c))
                else:                             # палец полки -> окно + пилот
                    wall_cuts.append((a2 - c, zs - c, b2 + c, zs + t + c))
                    mid = (a2 + b2) / 2.0
                    holes.append((t / 2.0, mid, p.pilot_d))
                    holes.append((W - t / 2.0, mid, p.pilot_d))
            shelf_parts.append(Part(f"Полка {i}", "xy", zs, t,
                                    (0.0, 0.0, W, ds), cuts, holes))
        else:
            # съёмная: меньше на зазор, отверстия полкодержателей в боковинах
            cl = p.shelf_clearance
            shelf_parts.append(Part(
                f"Полка {i}", "xy", zs, t,
                (t + cl, 0.0, W - t - cl, ds - cl), [], []))
            for k in range(-p.shelf_adjust_steps, p.shelf_adjust_steps + 1):
                z = zs + 32.0 * k
                if z < t + 10 or z > H - t - 10:
                    continue
                for y in (p.shelf_pin_inset, ds - p.shelf_pin_inset):
                    wall_blind.append((y, z, p.shelf_pin_d,
                                       p.shelf_pin_depth))

    # --- боковины (лев x 0..t, прав x W-t..W), пласть YZ (u=y, v=z) ---
    for name, x0, inner in (("Боковина Л", 0.0, "top"),
                            ("Боковина П", W - t, "base")):
        parts.append(Part(name, "yz", x0, t, (0.0, 0.0, D, H),
                          list(wall_cuts), [], list(wall_blind), inner))
    parts.extend(shelf_parts)

    # --- задник (y D-tb..D), пласть XZ (u=x, v=z) ---
    if p.has_back:
        cuts = []
        holes = []
        for a, b, kind in segH:                   # вертикальные края
            if kind == "A":                       # не палец -> вырез
                cuts.append((0.0, a - c, t + c, b + c))
                cuts.append((W - t - c, a - c, W, b + c))
            else:                                 # палец задника -> пилот
                mid = (a + b) / 2.0
                holes.append((t / 2.0, mid, p.pilot_d))
                holes.append((W - t / 2.0, mid, p.pilot_d))
        for a, b, kind in segW:                   # горизонтальные края
            if kind == "A":
                cuts.append((a - c, 0.0, b + c, t + c))
                cuts.append((a - c, H - t - c, b + c, H))
            else:
                mid = (a + b) / 2.0
                holes.append((mid, t / 2.0, p.pilot_d))
                holes.append((mid, H - t / 2.0, p.pilot_d))
        parts.append(Part("Задник", "xz", D - tb, tb,
                          (0.0, 0.0, W, H), cuts, holes))

    return {"parts": parts, "warnings": warnings}

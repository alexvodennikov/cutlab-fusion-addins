# -*- coding: utf-8 -*-
"""Расчётное ядро генератора фасадов. Чистый Python, без Fusion.

Петля по умолчанию: Blum CLIP top BLUMOTION 110°, крепление EXPANDO,
ответная планка прямая (linear) EXPANDO. Все константы сняты с
официального монтажного PDF Blum (MD-029/3 · 11.24), страницы 3–5:

- Чашка Ø35 (+0.2), глубина сверловки 10.5–13.0 (берём 13.0).
- Отступ сверловки TB (кромка фасада -> край чашки): 3..6 мм;
  центр чашки = TB + 17.5.
- Дюбели EXPANDO на петле: Ø8 (+0.1), разнос 45 мм (±22.5 от оси чашки),
  линия дюбелей на 9.5 мм от центра чашки вглубь фасада.
- Наложение (накладная дверь, планка H=8.5/D=0): FA = TB + 11.
- Прямая ответная планка EXPANDO: отверстия Ø10 (+0.1), шаг 32,
  первое на 20 мм от переднего торца боковины (второе на 52).

Все размеры в мм.
"""

from dataclasses import dataclass, field

# ----------------------------------------------------------------- Blum ----
BLUM = {
    "cup_d": 35.0,
    "cup_depth": 13.0,
    "tb_min": 3.0,
    "tb_max": 6.0,
    "cup_center_from_tb": 17.5,     # центр чашки = TB + 17.5 от кромки
    "dowel_d": 8.0,
    "dowel_depth": 12.0,
    "dowel_spacing": 45.0,          # между дюбелями (вдоль кромки)
    "dowel_offset": 9.5,            # от центра чашки вглубь фасада
    "overlay_const": 11.0,          # FA = TB + 11 (планка H=8.5, D=0)
    "plate_hole_d": 5.0,            # отверстие в боковине под планку
    "plate_hole_depth": 12.0,
    "plate_from_front": 20.0,       # первое отверстие от переднего торца
    "plate_pitch": 32.0,            # до второго отверстия
}


# --------------------------------------------------------------- params ----
@dataclass
class FacadeParams:
    # --- корпус ---
    cab_width: float = 600.0        # наружная ширина корпуса
    cab_height: float = 720.0       # высота боковины (зона фасада)
    wall_thickness: float = 18.0    # толщина боковины
    reveal: float = 2.0             # отступ кромки фасада от наружной
                                    # плоскости боковины (FA = wall - reveal)
    tb_override: float = 0.0        # 0 = авто из наложения

    # --- фасады ---
    thickness: float = 18.0
    n_facades: int = 1              # 1 | 2
    left_width: float = 0.0         # для n=2: 0 = симметрично, иначе чистовая
                                    # ширина левого фасада
    mid_gap: float = 3.0            # зазор между фасадами
    top_gap: float = 2.0            # зазор фасада сверху (от верха боковины)
    bottom_gap: float = 2.0
    offset_top: float = 0.0         # отступ зоны фасада сверху (например,
                                    # над дверью фасадный ящик)
    offset_bottom: float = 0.0      # отступ зоны фасада снизу (ящик под дверью)

    # --- кант ---
    band: float = 0.0               # толщина канта на сторону: 0 / 0.6 / 1 / 2
                                    # деталь пилится меньше на band с каждой
                                    # стороны (чистовой размер = деталь + кант)
    corner_r: float = 0.0           # скругление углов детали (R2), только
                                    # при band == 0

    # --- петли ---
    n_hinges: int = 0               # 0 = авто по высоте фасада
    hinge_edge_offset: float = 100.0  # ось крайних чашек от торца фасада
    hinge_side: str = "left"        # сторона петель ОДИНОЧНОГО фасада
                                    # ('left' | 'right'); у пары — всегда
                                    # наружные кромки


@dataclass
class Facade:
    index: int
    x0: float                       # левая чистовая кромка (коорд. корпуса)
    width: float                    # чистовая ширина (с кантом)
    height: float
    z0: float                       # низ фасада (коорд. корпуса)
    hinge_side: str                 # 'left' | 'right'
    hinge_z: list = field(default_factory=list)   # оси чашек от низа фасада
    # деталь под раскрой (за вычетом канта):
    detail_width: float = 0.0
    detail_height: float = 0.0


def auto_hinge_count(height):
    """Рекомендация Blum по числу петель от высоты двери."""
    if height <= 900:
        return 2
    if height <= 1600:
        return 3
    if height <= 2000:
        return 4
    return 5


def hinge_positions(height, n, edge_offset):
    """Оси чашек от низа фасада: крайние на edge_offset, остальные равномерно."""
    if n <= 1:
        return [height / 2.0]
    lo, hi = edge_offset, height - edge_offset
    return [lo + (hi - lo) * k / (n - 1) for k in range(n)]


def compute(p: FacadeParams):
    """Возвращает dict: fa, tb, facades[], warnings[]."""
    warnings = []

    # --- наложение и отступ сверловки ---
    fa_target = p.wall_thickness - p.reveal
    if p.tb_override and p.tb_override > 0:
        tb = p.tb_override
    else:
        tb = fa_target - BLUM["overlay_const"]
    tb_clamped = min(max(tb, BLUM["tb_min"]), BLUM["tb_max"])
    if abs(tb_clamped - tb) > 0.05:
        warnings.append(
            f"TB зажат в {tb_clamped:.1f} (расчётный {tb:.1f}, "
            f"допустимо {BLUM['tb_min']:.0f}–{BLUM['tb_max']:.0f})")
    tb = tb_clamped
    fa = tb + BLUM["overlay_const"]          # фактическое наложение

    # --- габарит фасадной зоны ---
    inner = p.cab_width - 2.0 * p.wall_thickness
    total_w = inner + 2.0 * fa               # чистовая ширина всех фасадов
    height = (p.cab_height - p.offset_top - p.offset_bottom
              - p.top_gap - p.bottom_gap)
    if height < 120:
        warnings.append(f"Высота фасада {height:.0f} мм — проверьте отступы")
    x_left = p.wall_thickness - fa           # левая кромка зоны фасадов

    # --- деление на фасады ---
    facades = []
    if p.n_facades <= 1:
        widths = [total_w]
        sides = ["right" if p.hinge_side == "right" else "left"]
    else:
        if p.left_width and p.left_width > 0:
            wl = p.left_width
            wr = total_w - p.mid_gap - wl
            if wr < 50:
                warnings.append("Правому фасаду осталось меньше 50 мм")
        else:
            wl = wr = (total_w - p.mid_gap) / 2.0
        widths = [wl, wr]
        sides = ["left", "right"]

    x = x_left
    for i, (w, side) in enumerate(zip(widths, sides), start=1):
        n_h = p.n_hinges if p.n_hinges > 0 else auto_hinge_count(height)
        f = Facade(
            index=i, x0=x, width=w, height=height, z0=p.offset_bottom + p.bottom_gap,
            hinge_side=side,
            hinge_z=hinge_positions(height, n_h, p.hinge_edge_offset),
            detail_width=w - 2.0 * p.band,
            detail_height=height - 2.0 * p.band)
        facades.append(f)
        x += w + p.mid_gap

    if p.band > 0 and p.corner_r > 0:
        warnings.append("Скругление углов доступно только без канта — "
                        "отключено")

    return {
        "fa": fa, "tb": tb,
        "cup_center_from_edge": tb + BLUM["cup_center_from_tb"],
        "facades": facades,
        "warnings": warnings,
    }

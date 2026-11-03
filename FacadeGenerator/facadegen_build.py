# -*- coding: utf-8 -*-
"""Построение фасадов в Fusion.

Параметрическая модель — ТРИ общих параметра на документ (Modify ->
Change Parameters): fg_facade_t (толщина), fg_gap (зазор фасада: между
фасадами и по верху/низу), fg_kant (кант на сторону). Они правят ВСЕ
фасады всех корпусов в файле разом. Всё остальное (позиции корпусов,
оси петель, сверловка Blum) запекается статикой — поэтому фасады разных
корпусов не конфликтуют между собой.

Система координат (корпусная): X — ширина, Y — глубина (перёд = 0,
фасад в −Y), Z — высота. origin — точка (xмин, yпередний, zниз) корпуса.

Грабли (см. память проекта): ось Y эскиза на xZ-плоскости смотрит в −Z —
якорный угол прямоугольника выбирается ближайшим к нарисованной точке;
тела из baseFeature нельзя резать CombineFeature — сверловка
параметрическим extrude-cut (participantBodies).
"""

import traceback

import adsk.core
import adsk.fusion

from facade_core import BLUM

MM = 0.1  # мм -> см


def _fmt(v):
    """Число мм для вставки в выражение."""
    return f"{v:.4f} mm"


# ------------------------------------------------------- user parameters --
def _ensure_param(design, name, expr, comment=""):
    up = design.userParameters
    ex = up.itemByName(name)
    if ex:
        ex.expression = expr
        if comment:
            ex.comment = comment
    else:
        up.add(name, adsk.core.ValueInput.createByString(expr),
               "mm", comment)


def _setup_params(design, p):
    _ensure_param(design, "fg_facade_t", _fmt(p.thickness),
                  "Толщина фасада (все фасады)")
    _ensure_param(design, "fg_gap", _fmt(p.mid_gap),
                  "Зазор фасада: между фасадами и по верху/низу")
    _ensure_param(design, "fg_kant", _fmt(p.band),
                  "Кант на сторону (деталь меньше чистового)")


# ------------------------------------------------------------- sketching --
def _sketch_on_plane(comp, base_plane, offset_mm, name):
    planes = comp.constructionPlanes
    pi = planes.createInput()
    pi.setByOffset(base_plane,
                   adsk.core.ValueInput.createByReal(offset_mm * MM))
    plane = planes.add(pi)
    plane.name = f"pl_{name}"
    sk = comp.sketches.add(plane)
    sk.name = name
    return sk


def _mp(sk, x_mm, y_mm, z_mm):
    p = sk.modelToSketchSpace(adsk.core.Point3D.create(
        x_mm * MM, y_mm * MM, z_mm * MM))
    p.z = 0
    return p


def _circle(sk, x_mm, y_mm, z_mm, d_mm):
    sk.sketchCurves.sketchCircles.addByCenterRadius(
        _mp(sk, x_mm, y_mm, z_mm), d_mm / 2.0 * MM)


def _axis_map(sk):
    def dominant(v):
        ax = [("x", v.x), ("y", v.y), ("z", v.z)]
        return max(ax, key=lambda t: abs(t[1]))[0]
    return dominant(sk.xDirection), dominant(sk.yDirection)


def _rect_param(sk, p1_mm, p2_mm, x_expr, z_expr, w_expr, h_expr, log):
    """Прямоугольник с размерами-формулами (позиция угла + ширина/высота).
    Якорный угол — ближайший к p1 в координатах эскиза."""
    a = _mp(sk, *p1_mm)
    b = _mp(sk, *p2_mm)
    lines = sk.sketchCurves.sketchLines.addTwoPointRectangle(a, b)
    try:
        ax_x, _ = _axis_map(sk)
        h_first = ax_x == "x"          # sketch-X вдоль модельной X
        pts = [ln.startSketchPoint for ln in lines]
        corner = min(pts, key=lambda s: ((s.geometry.x - a.x) ** 2 +
                                         (s.geometry.y - a.y) ** 2))
        dims = sk.sketchDimensions
        H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
        V = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
        g = corner.geometry
        d1 = dims.addDistanceDimension(
            sk.originPoint, corner, H,
            adsk.core.Point3D.create(g.x + 1, g.y + 0.4, 0))
        d1.parameter.expression = x_expr if h_first else z_expr
        d2 = dims.addDistanceDimension(
            sk.originPoint, corner, V,
            adsk.core.Point3D.create(g.x + 0.4, g.y + 1, 0))
        d2.parameter.expression = z_expr if h_first else x_expr
        xs = sorted(pts, key=lambda s: s.geometry.x)
        ys = sorted(pts, key=lambda s: s.geometry.y)
        dw = dims.addDistanceDimension(
            xs[0], xs[-1], H,
            adsk.core.Point3D.create(g.x + 2, g.y - 1, 0))
        dw.parameter.expression = w_expr if h_first else h_expr
        dh = dims.addDistanceDimension(
            ys[0], ys[-1], V,
            adsk.core.Point3D.create(g.x - 1, g.y + 2, 0))
        dh.parameter.expression = h_expr if h_first else w_expr
    except Exception:
        log.append(f"параметризация контура: {traceback.format_exc(limit=1)}")


def _cut_all_profiles(comp, sk, depth_mm, targets):
    """Симметричный вырез всех профилей эскиза (глубина на сторону)."""
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))
    if profs.count == 0:
        return None
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(
        profs, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ei.setSymmetricExtent(
        adsk.core.ValueInput.createByReal(2.0 * depth_mm * MM), True)
    ei.participantBodies = list(targets)
    return ext.add(ei)


def _new_component(root, base_name):
    occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
    comp = occ.component
    name = base_name
    n = 1
    while True:
        try:
            comp.name = name
            break
        except Exception:
            n += 1
            name = f"{base_name} {n}"
            if n > 50:
                break
    return comp


# ------------------------------------------------------------------ build --
def build_facades(design, p, lay, origin=(0.0, 0.0, 0.0),
                  wall_bodies=None, log=None):
    if log is None:
        log = []
    ox, oy, oz = origin
    _setup_params(design, p)

    root = design.rootComponent
    comp = _new_component(root, "Фасады")

    th = p.thickness
    cup_from_edge = lay["cup_center_from_edge"]

    # статические числа этого корпуса (запекаются в формулы)
    inner = p.cab_width - 2.0 * p.wall_thickness
    total = inner + 2.0 * lay["fa"]          # чистовая ширина фасадной зоны
    x_left = ox + p.wall_thickness - lay["fa"]
    n = len(lay["facades"])

    for f in lay["facades"]:
        i = f.index
        # выражения позиции/размера детали через fg_gap / fg_kant
        if n == 1:
            x_expr = f"{_fmt(x_left)} + fg_kant"
            w_expr = f"{_fmt(total)} - 2 * fg_kant"
        elif p.left_width and p.left_width > 0:
            if i == 1:
                x_expr = f"{_fmt(x_left)} + fg_kant"
                w_expr = f"{_fmt(p.left_width)} - 2 * fg_kant"
            else:
                x_expr = f"{_fmt(x_left + p.left_width)} + fg_gap + fg_kant"
                w_expr = (f"{_fmt(total - p.left_width)} - fg_gap "
                          f"- 2 * fg_kant")
        else:
            if i == 1:
                x_expr = f"{_fmt(x_left)} + fg_kant"
            else:
                x_expr = (f"{_fmt(x_left + total / 2.0)} + fg_gap / 2 "
                          f"+ fg_kant")
            w_expr = f"({_fmt(total)} - fg_gap) / 2 - 2 * fg_kant"
        z_expr = f"{_fmt(oz)} + fg_gap + fg_kant"
        h_expr = f"{_fmt(p.cab_height)} - 2 * fg_gap - 2 * fg_kant"

        try:
            dx0 = f.x0 + p.band + ox
            dz0 = f.z0 + p.band + oz
            sk = _sketch_on_plane(comp, comp.xZConstructionPlane, oy,
                                  f"facade_{i}")
            _rect_param(sk, (dx0, oy, dz0),
                        (dx0 + f.detail_width, oy, dz0 + f.detail_height),
                        x_expr, z_expr, w_expr, h_expr, log)
            ext = comp.features.extrudeFeatures
            ei = ext.createInput(
                sk.profiles.item(0),
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
            ei.setDistanceExtent(False, adsk.core.ValueInput.createByReal(
                -th * MM))
            feat = ext.add(ei)
            body = feat.bodies.item(0) if feat.bodies.count else None
            if body is None:
                log.append(f"фасад {i}: нет тела")
                continue
            body.name = f"Фасад {i}"
            try:
                feat.extentOne.distance.expression = "-fg_facade_t"
            except Exception:
                try:
                    feat.extentOne.distance.expression = "fg_facade_t"
                except Exception:
                    log.append(f"фасад {i}: толщина не параметризована")

            # скругление углов (только без канта) — статичное
            if p.band <= 0 and p.corner_r > 0:
                edges = adsk.core.ObjectCollection.create()
                for e in body.edges:
                    g = e.geometry
                    if isinstance(g, adsk.core.Line3D):
                        d = g.startPoint.vectorTo(g.endPoint)
                        if abs(d.x) < 1e-9 and abs(d.z) < 1e-9:
                            edges.add(e)
                if edges.count:
                    fil = comp.features.filletFeatures
                    fi = fil.createInput()
                    fi.edgeSetInputs.addConstantRadiusEdgeSet(
                        edges,
                        adsk.core.ValueInput.createByReal(p.corner_r * MM),
                        False)
                    fil.add(fi)

            # --- сверловка чашек и дюбелей (статичная, Blum) ---
            skd = _sketch_on_plane(comp, comp.xZConstructionPlane, oy,
                                   f"dowels_{i}")
            skc = _sketch_on_plane(comp, comp.xZConstructionPlane, oy,
                                   f"cups_{i}")
            for zh in f.hinge_z:
                z_abs = f.z0 + zh + oz
                if f.hinge_side == "left":
                    x_cup = f.x0 + cup_from_edge + ox
                    x_dw = x_cup + BLUM["dowel_offset"]
                else:
                    x_cup = f.x0 + f.width - cup_from_edge + ox
                    x_dw = x_cup - BLUM["dowel_offset"]
                half = BLUM["dowel_spacing"] / 2.0
                _circle(skd, x_dw, oy, z_abs + half, BLUM["dowel_d"])
                _circle(skd, x_dw, oy, z_abs - half, BLUM["dowel_d"])
                _circle(skc, x_cup, oy, z_abs, BLUM["cup_d"])
            _cut_all_profiles(comp, skd, BLUM["dowel_depth"], [body])
            _cut_all_profiles(comp, skc, BLUM["cup_depth"], [body])

            log.append(f"Фасад {i}: {f.detail_width:.1f}×"
                       f"{f.detail_height:.1f}×{th:.0f} "
                       f"(чистовой {f.width:.1f}×{f.height:.1f}), "
                       f"петель {len(f.hinge_z)}, кромка "
                       f"{'левая' if f.hinge_side == 'left' else 'правая'}")
        except Exception:
            log.append(f"фасад {i}: {traceback.format_exc(limit=1)}")

    _plate_drilling(design, comp, p, lay, origin, wall_bodies, log)
    log.append("Параметры (общие на документ): fg_facade_t, fg_gap, fg_kant")
    return log


def _plate_drilling(design, comp, p, lay, origin, wall_bodies, log):
    """Сверловка прямых ответных планок (Ø5×12 на 20/52 от торца) —
    статичная. Если боковины выбраны — режем их, иначе тела-свёрла."""
    ox, oy, oz = origin
    d = BLUM["plate_hole_d"]
    depth = BLUM["plate_hole_depth"]
    y1 = BLUM["plate_from_front"] + oy
    y2 = y1 + BLUM["plate_pitch"]

    for f in lay["facades"]:
        i = f.index
        if f.hinge_side == "left":
            x_face = p.wall_thickness + ox
            direction = 1.0
        else:
            x_face = p.cab_width - p.wall_thickness + ox
            direction = -1.0

        try:
            sk = _sketch_on_plane(comp, comp.yZConstructionPlane,
                                  x_face, f"plates_{i}")
            for zh in f.hinge_z:
                z_abs = f.z0 + zh + oz
                _circle(sk, x_face, y1, z_abs, d)
                _circle(sk, x_face, y2, z_abs, d)
            if wall_bodies:
                _cut_all_profiles(comp, sk, depth, wall_bodies)
                log.append(f"Планки фасада {i}: сверловка в боковине "
                           f"({len(f.hinge_z)}×2 отв. Ø{d:.0f})")
            else:
                profs = adsk.core.ObjectCollection.create()
                for j in range(sk.profiles.count):
                    profs.add(sk.profiles.item(j))
                ext = comp.features.extrudeFeatures
                ei = ext.createInput(
                    profs,
                    adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
                ei.setDistanceExtent(
                    False, adsk.core.ValueInput.createByReal(
                        -direction * depth * MM))
                feat = ext.add(ei)
                for j in range(feat.bodies.count):
                    feat.bodies.item(j).name = f"Сверло планки {i}"
                log.append(f"Планки фасада {i}: тела-свёрла")
        except Exception:
            log.append(f"планки {i}: {traceback.format_exc(limit=1)}")

# -*- coding: utf-8 -*-
"""Построение корпуса в Fusion. Имя модуля уникально (cabinetgen_*).

Каждая деталь — ОТДЕЛЬНЫЙ компонент (важно для Arrange) внутри
компонента корпуса. Детали строятся экструзией полного контура +
сквозные вырезы гребёнок/пазов + пилоты (parametric extrude-cut,
participantBodies — тела из baseFeature резать нельзя).

Заходные скругления: внешние углы ШИПОВ (рёбра вдоль толщины на концах
пальцев), пазы остаются прямыми — внутренние углы пользователь закроет
dogbones. Геометрия статичная: изменения — перезапуском плагина.
"""

import traceback

import adsk.core
import adsk.fusion

MM = 0.1  # мм -> см

_PLANES = {
    "xy": ("xYConstructionPlane", lambda u, v, w: (u, v, w)),
    "yz": ("yZConstructionPlane", lambda u, v, w: (w, u, v)),
    "xz": ("xZConstructionPlane", lambda u, v, w: (u, w, v)),
}


def _model_pt(plane, u, v, w, origin):
    x, y, z = _PLANES[plane][1](u, v, w)
    return (x + origin[0], y + origin[1], z + origin[2])


def _sketch_on(comp, plane, c0_mm, name, origin):
    # смещение плоскости тоже в мировых координатах (origin по нормали)
    normal_off = {"xy": origin[2], "yz": origin[0], "xz": origin[1]}[plane]
    planes = comp.constructionPlanes
    pi = planes.createInput()
    base = getattr(comp, _PLANES[plane][0])
    pi.setByOffset(base, adsk.core.ValueInput.createByReal(
        (c0_mm + normal_off) * MM))
    pl = planes.add(pi)
    pl.name = f"pl_{name}"
    sk = comp.sketches.add(pl)
    sk.name = name
    return sk


def _mp(sk, plane, u, v, c0, origin):
    x, y, z = _model_pt(plane, u, v, c0, origin)
    p = sk.modelToSketchSpace(
        adsk.core.Point3D.create(x * MM, y * MM, z * MM))
    p.z = 0
    return p


def _rect(sk, plane, r, c0, origin):
    a = _mp(sk, plane, r[0], r[1], c0, origin)
    b = _mp(sk, plane, r[2], r[3], c0, origin)
    sk.sketchCurves.sketchLines.addTwoPointRectangle(a, b)


def _extrude(comp, sk, dist_mm, operation, targets=None, name=None):
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))
    if profs.count == 0:
        return None
    ext = comp.features.extrudeFeatures
    ei = ext.createInput(profs, operation)
    ei.setDistanceExtent(False,
                         adsk.core.ValueInput.createByReal(dist_mm * MM))
    if targets is not None:
        ei.participantBodies = list(targets)
    feat = ext.add(ei)
    if name and feat.bodies.count:
        try:
            feat.bodies.item(0).name = name
        except Exception:
            pass
    return feat


def _new_component(parent_comp_occs, base_name):
    occ = parent_comp_occs.addNewComponent(adsk.core.Matrix3D.create())
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
            if n > 99:
                break
    return comp


def _ease_fillets(body, part, p, origin, log):
    """Заходные скругления внешних углов шипов: рёбра вдоль нормали
    пласти на концевых плоскостях пальцев (не на углах детали)."""
    if p.ease_r <= 0:
        return
    W, H, D = p.width, p.height, p.depth
    ox, oy, oz = origin
    eps = 0.5 * MM
    normal = {"xy": (0, 0, 1), "yz": (1, 0, 0), "xz": (0, 0, 1)}
    # концевые плоскости пальцев и запрещённые (углы детали) по осям, мм
    if part.plane == "xy":
        ends = [("x", ox), ("x", ox + W)]
        forbid = [("y", oy), ("y", oy + D)]
    elif part.plane == "yz":
        ends = [("z", oz), ("z", oz + H)]
        forbid = [("y", oy), ("y", oy + D)]
    else:  # задник
        ends = [("x", ox), ("x", ox + W), ("z", oz), ("z", oz + H)]
        forbid = []

    def coord(pt, axis):
        return {"x": pt.x, "y": pt.y, "z": pt.z}[axis] * 10.0  # -> мм

    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        g = e.geometry
        if not isinstance(g, adsk.core.Line3D):
            continue
        d = g.startPoint.vectorTo(g.endPoint)
        d.normalize()
        # ребро вдоль нормали пласти?
        if part.plane == "yz":
            along = abs(d.x) > 0.99
        elif part.plane == "xy":
            along = abs(d.z) > 0.99
        else:
            along = abs(d.y) > 0.99
        if not along:
            continue
        m = g.startPoint
        on_end = any(abs(coord(m, ax) - val) < 0.5 for ax, val in ends)
        on_forbid = any(abs(coord(m, ax) - val) < 0.5
                        for ax, val in forbid)
        if on_end and not on_forbid:
            edges.add(e)
    if edges.count == 0:
        return
    try:
        comp = body.parentComponent
        fil = comp.features.filletFeatures
        fi = fil.createInput()
        fi.edgeSetInputs.addConstantRadiusEdgeSet(
            edges, adsk.core.ValueInput.createByReal(p.ease_r * MM), False)
        fil.add(fi)
    except Exception:
        log.append(f"{part.name}: скругления шипов не наложились "
                   f"({edges.count} рёбер)")


def build_cabinet(design, p, lay, log=None):
    if log is None:
        log = []
    origin = (p.origin_x, p.origin_y, p.origin_z)
    root = design.rootComponent
    cab = _new_component(root.occurrences, "Корпус")

    for part in lay["parts"]:
        try:
            comp = _new_component(cab.occurrences, part.name)
            sk = _sketch_on(comp, part.plane, part.c0, f"outline", origin)
            _rect(sk, part.plane, part.rect, part.c0, origin)
            feat = _extrude(
                comp, sk, part.th,
                adsk.fusion.FeatureOperations.NewBodyFeatureOperation,
                name=part.name)
            body = feat.bodies.item(0) if feat and feat.bodies.count else None
            if body is None:
                log.append(f"{part.name}: нет тела")
                continue

            if part.cuts:
                skc = _sketch_on(comp, part.plane, part.c0, "cuts", origin)
                for r in part.cuts:
                    _rect(skc, part.plane, r, part.c0, origin)
                _extrude(comp, skc, part.th,
                         adsk.fusion.FeatureOperations.CutFeatureOperation,
                         targets=[body])

            if part.holes:
                skh = _sketch_on(comp, part.plane, part.c0, "pilots", origin)
                for (u, v, d) in part.holes:
                    ctr = _mp(skh, part.plane, u, v, part.c0, origin)
                    skh.sketchCurves.sketchCircles.addByCenterRadius(
                        ctr, d / 2.0 * MM)
                _extrude(comp, skh, part.th,
                         adsk.fusion.FeatureOperations.CutFeatureOperation,
                         targets=[body])

            if part.blind_holes:
                # глухие отверстия с ВНУТРЕННЕЙ пласти (полкодержатели)
                inner_top = part.inner_face == "top"
                c_face = part.c0 + (part.th if inner_top else 0.0)
                skb = _sketch_on(comp, part.plane, c_face, "pins", origin)
                for (u, v, d, depth) in part.blind_holes:
                    ctr = _mp(skb, part.plane, u, v, c_face, origin)
                    skb.sketchCurves.sketchCircles.addByCenterRadius(
                        ctr, d / 2.0 * MM)
                depth = part.blind_holes[0][3]
                _extrude(comp, skb, -depth if inner_top else depth,
                         adsk.fusion.FeatureOperations.CutFeatureOperation,
                         targets=[body])

            _ease_fillets(body, part, p, origin, log)

            log.append(f"{part.name}: "
                       f"{part.rect[2]-part.rect[0]:.0f}×"
                       f"{part.rect[3]-part.rect[1]:.0f}×{part.th:.0f}, "
                       f"вырезов {len(part.cuts)}, пилотов {len(part.holes)}")
        except Exception:
            log.append(f"{part.name}: {traceback.format_exc(limit=1)}")

    return log

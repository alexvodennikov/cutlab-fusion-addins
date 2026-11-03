# -*- coding: utf-8 -*-
"""Построение короба в Fusion. Имя модуля уникально (boxgen_*).

Каждая деталь — отдельный компонент внутри компонента «Короб».
Экструзия контура + сквозные вырезы (гребёнка) + сквозные отверстия +
глухие карманы/гнёзда с указанной пласти (Cabineo, пилоты Ø5, магниты).
Карман Cabineo — три пересекающихся окружности в одном эскизе: собираются
все профили эскиза и режутся одной операцией.
"""

import traceback

import adsk.core
import adsk.fusion

MM = 0.1

_PLANES = {
    "xy": ("xYConstructionPlane", lambda u, v, w: (u, v, w)),
    "yz": ("yZConstructionPlane", lambda u, v, w: (w, u, v)),
    "xz": ("xZConstructionPlane", lambda u, v, w: (u, w, v)),
}


def _model_pt(plane, u, v, w, origin):
    x, y, z = _PLANES[plane][1](u, v, w)
    return (x + origin[0], y + origin[1], z + origin[2])


def _sketch_on(comp, plane, c0_mm, name, origin):
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


def build_box(design, p, lay, log=None):
    if log is None:
        log = []
    origin = (p.origin_x, p.origin_y, p.origin_z)
    root = design.rootComponent
    box_comp = _new_component(root.occurrences, "Короб")

    for part in lay["parts"]:
        try:
            comp = _new_component(box_comp.occurrences, part.name)
            sk = _sketch_on(comp, part.plane, part.c0, "outline", origin)
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
                skh = _sketch_on(comp, part.plane, part.c0, "thru", origin)
                for (u, v, d) in part.holes:
                    ctr = _mp(skh, part.plane, u, v, part.c0, origin)
                    skh.sketchCurves.sketchCircles.addByCenterRadius(
                        ctr, d / 2.0 * MM)
                _extrude(comp, skh, part.th,
                         adsk.fusion.FeatureOperations.CutFeatureOperation,
                         targets=[body])

            # глухие карманы/гнёзда, сгруппированы по (пласть, глубина)
            groups = {}
            for face, depth, circles in part.pockets:
                groups.setdefault((face, round(depth, 2)), []).extend(circles)
            for gi, ((face, depth), circles) in enumerate(groups.items()):
                c_face = part.c0 + (part.th if face == "far" else 0.0)
                skp = _sketch_on(comp, part.plane, c_face,
                                 f"pockets_{gi}", origin)
                for (u, v, d) in circles:
                    ctr = _mp(skp, part.plane, u, v, c_face, origin)
                    skp.sketchCurves.sketchCircles.addByCenterRadius(
                        ctr, d / 2.0 * MM)
                _extrude(comp, skp, -depth if face == "far" else depth,
                         adsk.fusion.FeatureOperations.CutFeatureOperation,
                         targets=[body])

            log.append(f"{part.name}: "
                       f"{part.rect[2] - part.rect[0]:.0f}×"
                       f"{part.rect[3] - part.rect[1]:.0f}×{part.th:.0f}, "
                       f"гнёзд {len(part.pockets)}, "
                       f"сквозных {len(part.holes)}, "
                       f"вырезов {len(part.cuts)}")
        except Exception:
            log.append(f"{part.name}: {traceback.format_exc(limit=1)}")

    return log

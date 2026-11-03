# -*- coding: utf-8 -*-
"""Построение ящика Ultrabox в Fusion 360.

Использует TemporaryBRepManager + baseFeature: все тела создаются в мировых
координатах (мм -> см), без эскизов. Каждая деталь -- отдельное тело в новом
компоненте Ultrabox_H<h>_NL<nl>_LW<lw>.
"""
import math

import adsk.core
import adsk.fusion

try:
    import ultrabox_core as core
except ImportError:
    from . import ultrabox_core as core

MM = 0.1  # мм -> см (внутренние единицы Fusion)

_XD = adsk.core.Vector3D.create(1, 0, 0)
_YD = adsk.core.Vector3D.create(0, 1, 0)


def _p(x, y, z):
    return adsk.core.Point3D.create(x * MM, y * MM, z * MM)


def _box(tmp, x0, y0, z0, dx, dy, dz):
    c = adsk.core.Point3D.create((x0 + dx / 2.0) * MM, (y0 + dy / 2.0) * MM,
                                 (z0 + dz / 2.0) * MM)
    obb = adsk.core.OrientedBoundingBox3D.create(c, _XD, _YD,
                                                 abs(dx) * MM, abs(dy) * MM, abs(dz) * MM)
    return tmp.createBox(obb)


def _cyl(tmp, p1, p2, d):
    r = d / 2.0 * MM
    return tmp.createCylinderOrCone(p1, r, p2, r)


def _set_unique_name(component, base):
    try:
        component.name = base
        return
    except Exception:
        pass
    for i in range(2, 100):
        try:
            component.name = '%s (%d)' % (base, i)
            return
        except Exception:
            continue


def _add_bodies(component, items):
    """items: [(имя, temp-brep, ключ материала)] -> [(body, ключ)]."""
    bf = component.features.baseFeatures.add()
    bf.startEdit()
    out = []
    for name, brep, key in items:
        nb = component.bRepBodies.add(brep, bf)
        nb.name = name
        out.append((nb, key))
    bf.finishEdit()
    return out


def _appearance(design, name):
    try:
        a = design.appearances.itemByName(name)
        if a:
            return a
        lib = adsk.core.Application.get().materialLibraries.itemByName('Fusion Appearance Library')
        src = lib.appearances.itemByName(name)
        if src:
            return design.appearances.addByCopy(src, name)
    except Exception:
        pass
    return None


def build(cfg, offset=(0.0, 0.0, 0.0), facade_drill=True, rot_z_deg=0.0):
    """Строит ящик, возвращает (occurrence, результат compute).

    rot_z_deg: поворот ящика вокруг Z (вокруг локального 0,0,0) ДО переноса
    на offset — для ящиков, открывающихся не в -Y (0 = как раньше).
    """
    res = core.compute(cfg)
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    root = design.rootComponent
    tmp = adsk.fusion.TemporaryBRepManager.get()

    tr = adsk.core.Matrix3D.create()
    tr.translation = adsk.core.Vector3D.create(offset[0] * MM, offset[1] * MM, offset[2] * MM)
    occ = root.occurrences.addNewComponent(tr)
    comp = occ.component
    comp.name = 'Ultrabox_H%d_NL%d_LW%d%s' % (res['h'], res['nl'], int(res['lw']),
                                              '_inner' if res['inner'] else '')

    lw = res['lw']
    lay = res['layout']
    bodies = []       # металл и служебные тела -> в основной компонент
    sheet_parts = []  # (имя подкомпонента, brep, ключ) -> отдельные подкомпоненты

    # дно
    b = lay['bottom']
    sheet_parts.append(('Дно', _box(tmp, b['x'], b['y'], b['z'], b['w'], b['l'], b['t']), 'wood'))
    # задняя стенка
    bk = lay['back']
    sheet_parts.append(('Задняя стенка',
                        _box(tmp, bk['x'], bk['y'], bk['z'], bk['w'], bk['t'], bk['hgt']), 'wood'))

    # боковины (металл, упрощённо: стенка + полка под дно) и направляющие
    s = lay['sides']
    sl = lay['slide']
    for side, x_wall, x_flange in (('L', 3.0, s['zone_w']), ('R', lw - 3.0 - s['wall_t'], lw - s['zone_w'])):
        wall = _box(tmp, x_wall, s['y0'], 8.0, s['wall_t'], s['length'], s['hgt'] + 2.0)
        # полка-опора дна до кромки дна (37.5 от стенки корпуса)
        if side == 'L':
            flange = _box(tmp, s['zone_w'], s['y0'], b['z'] - 2.0, b['x'] - s['zone_w'] + 2.0, s['length'], 2.0)
        else:
            flange = _box(tmp, b['x'] + b['w'] - 2.0, s['y0'], b['z'] - 2.0,
                          lw - s['zone_w'] - (b['x'] + b['w']) + 2.0, s['length'], 2.0)
        tmp.booleanOperation(wall, flange, adsk.fusion.BooleanTypes.UnionBooleanType)
        bodies.append(('Bokovina_' + side, wall, 'metal'))
        x_sl = 0.0 if side == 'L' else lw - sl['w']
        bodies.append(('Napravlyayushchaya_' + side,
                       _box(tmp, x_sl, sl['y0'], 0.0, sl['w'], sl['length'], sl['hgt']), 'metal'))

    # фасад с присадкой (наружный ящик)
    if res['facade']:
        f = res['facade']
        fac = _box(tmp, f['x'], f['y'], f['z'], f['w'], f['t'], f['hgt'])
        y_rear = f['y'] + f['t']  # задняя плоскость фасада
        for h in (res['facade_holes'] if facade_drill else []):
            tool = _cyl(tmp, _p(h['x'], y_rear + 0.5, h['z']),
                        _p(h['x'], y_rear - h['depth'], h['z']), h['d'])
            tmp.booleanOperation(fac, tool, adsk.fusion.BooleanTypes.DifferenceBooleanType)
        sheet_parts.append(('Фасад', fac, 'facade'))

    # внутренний ящик: металлическая передняя панель
    if res['inner']:
        w_mf = lw - core.INNER_FRONT_W_OFFSET
        bodies.append(('Metal_front',
                       _box(tmp, (lw - w_mf) / 2.0, s['y0'] - 1.5, bk['z'], w_mf, 1.5, float(res['h'])),
                       'metal'))

    # тела-сверла для присадки корпуса (по одному телу на сторону)
    if cfg.get('cab_drill', 'bodies') != 'none':
        for side, x0, x1 in (('L', 0.0, -core.CAB_HOLE_DEPTH), ('R', lw, lw + core.CAB_HOLE_DEPTH)):
            drill = None
            for h in res['cabinet_holes']:
                c = _cyl(tmp, _p(x0, h['y'], h['z']), _p(x1, h['y'], h['z']), h['d'])
                if drill is None:
                    drill = c
                else:
                    tmp.booleanOperation(drill, c, adsk.fusion.BooleanTypes.UnionBooleanType)
            bodies.append(('DRILL_korpus_' + side, drill, 'drill'))

    if rot_z_deg:
        _rm = adsk.core.Matrix3D.create()
        _rm.setToRotation(math.radians(rot_z_deg),
                          adsk.core.Vector3D.create(0, 0, 1),
                          adsk.core.Point3D.create(0, 0, 0))
        for _n, _b, _k in bodies:
            tmp.transform(_b, _rm)
        for _n, _b, _k in sheet_parts:
            tmp.transform(_b, _rm)

    created = _add_bodies(comp, bodies)
    # листовые детали -- отдельными подкомпонентами (раскрой/ЧПУ)
    ident = adsk.core.Matrix3D.create()
    for part_name, brep, key in sheet_parts:
        sub = comp.occurrences.addNewComponent(ident)
        _set_unique_name(sub.component, part_name)
        created += _add_bodies(sub.component, [(part_name, brep, key)])

    apps = dict(
        wood=_appearance(design, 'Oak - Semigloss'),
        facade=_appearance(design, 'Oak'),
        metal=_appearance(design, 'Aluminum - Anodized Glossy (Grey)'),
        drill=_appearance(design, 'Acrylic (Red)'),
    )
    for nb, key in created:
        a = apps.get(key)
        if a:
            try:
                nb.appearance = a
            except Exception:
                pass
    return occ, res


def cut_cabinet(target_bodies, res, offset=(0.0, 0.0, 0.0)):
    """Вырезает присадку под направляющие в телах боковин корпуса.

    Эскиз окружностей на плоскости внутренней стенки + симметричный extrude-cut
    только по participantBodies (тела Ultrabox не затрагиваются).
    Тела из baseFeature нельзя использовать как инструменты Combine
    (ALL_TOOL_BODY_REFERENCE_LOST), поэтому режем обычной параметрической операцией.
    """
    if not target_bodies:
        return 0
    design = adsk.fusion.Design.cast(adsk.core.Application.get().activeProduct)
    root = design.rootComponent
    tl_start = design.timeline.count
    ox, oy, oz = offset
    n = 0
    for x_local in (0.0, res['lw']):
        x_plane = (ox + x_local) * MM
        pi = root.constructionPlanes.createInput()
        pi.setByOffset(root.yZConstructionPlane, adsk.core.ValueInput.createByReal(x_plane))
        plane = root.constructionPlanes.add(pi)
        plane.isLightBulbOn = False
        sk = root.sketches.add(plane)
        sk.name = 'Ultrabox_prisadka'
        for h in res['cabinet_holes']:
            wp = adsk.core.Point3D.create(x_plane, (oy + h['y']) * MM, (oz + h['z']) * MM)
            sk.sketchCurves.sketchCircles.addByCenterRadius(
                sk.modelToSketchSpace(wp), h['d'] / 2.0 * MM)
        profs = adsk.core.ObjectCollection.create()
        for p in sk.profiles:
            profs.add(p)
        ei = root.features.extrudeFeatures.createInput(
            profs, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ei.setSymmetricExtent(
            adsk.core.ValueInput.createByReal(2 * CAB_HOLE_DEPTH_CM), True)
        ei.participantBodies = list(target_bodies)
        try:
            root.features.extrudeFeatures.add(ei)
            n += 1
        except Exception:
            pass
        sk.isVisible = False
    try:
        if design.timeline.count > tl_start:
            g = design.timeline.timelineGroups.add(tl_start, design.timeline.count - 1)
            g.name = 'Ultrabox присадка корпуса'
    except Exception:
        pass
    return n


CAB_HOLE_DEPTH_CM = core.CAB_HOLE_DEPTH * MM

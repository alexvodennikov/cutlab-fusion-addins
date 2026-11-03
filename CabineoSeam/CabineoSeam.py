# -*- coding: utf-8 -*-
"""CabineoSeam — Fusion add-in: Cabineo 8 на шов между двумя выбранными
панелями в произвольной ориентации.

Выбираются две плоские грани:
  1) пласть детали A, ГДЕ БУДУТ ШЛЯПКИ — в неё фрезеруются карманы;
  2) пласть детали B, к которой примыкает торец A, — в неё сверлятся пилоты.

Плагин находит линию пересечения плоскостей (ось шва), перекрытие деталей
вдоль неё и раскладывает коннекторы (количество или авто по шагу).

Фрезеровка — официальный лист Lamello (Cabineo 02/24, Bund aufliegend,
фреза >=Ø10): карман 3×Ø15 глубиной 11 (центры 3.6/14.8/26.0 от кромки,
открыт в торец), пилот Ø5×8 (X = 8) на оси 5 мм от карманной пласти.

Направление реза определяется по факту (контроль объёма тела): работает
при любой ориентации деталей. Тела из baseFeature (импорт STEP) резать
нельзя — плагин сообщит, что тело не изменилось.
"""

import math
import os
import sys
import traceback

import adsk.core
import adsk.fusion

MM = 0.1

CAB_CUP_D = 15.0
CAB_CUP_CENTERS = (3.6, 14.8, 26.0)
CAB_POCKET_DEPTH = 11.0
CAB_PILOT_D = 5.0
CAB_PILOT_DEPTH = 8.0    # X = 8 mm (Cabineo 8): глубина пилота от плоскости стыка, лист Lamello 02/24
CAB_AXIS_X = 5.0         # ось пилота в 5 мм от карманной пласти (лист Lamello: 5 / D-5); было 8 — ошибка, X это глубина
CAB_MIN_EDGE = 20.0

_app = None
_ui = None
_handlers = []

CMD_ID = "cabineoSeamCmd"
CMD_NAME = "Cabineo на шов"
CMD_DESC = ("Карманы Cabineo 8 и пилоты на шов между двумя выбранными "
            "панелями (официальная фрезеровка Lamello)")
PANEL_ID = "SolidCreatePanel"
WORKSPACE_ID = "FusionSolidEnvironment"


def _fail(where):
    if _ui:
        _ui.messageBox(f"{where}:\n{traceback.format_exc()}")


def _mm(inp):
    return inp.value * 10.0


# ------------------------------------------------------------------ vector
def _v(a):
    return (a.x, a.y, a.z)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _norm(a):
    l = math.sqrt(_dot(a, a))
    return (a[0] / l, a[1] / l, a[2] / l) if l > 1e-12 else (0, 0, 0)


def _face_normal(face):
    """Наружная нормаль грани в точке её центроида, мм-мир."""
    ev = face.evaluator
    ok, pt = ev.getPointAtParameter(
        adsk.core.Point2D.create(*_face_mid_param(face)))
    ok2, n = ev.getNormalAtPoint(pt)
    return _norm(_v(n)), _mul(_v(pt), 10.0)


def _face_mid_param(face):
    pr = face.evaluator.parametricRange()
    return ((pr.minPoint.x + pr.maxPoint.x) / 2.0,
            (pr.minPoint.y + pr.maxPoint.y) / 2.0)


def _body_interval(body, origin, direction):
    """Проекция bbox тела на направление (мм) относительно origin."""
    bb = body.boundingBox
    mn = _mul(_v(bb.minPoint), 10.0)
    mx = _mul(_v(bb.maxPoint), 10.0)
    lo, hi = 1e18, -1e18
    for x in (mn[0], mx[0]):
        for y in (mn[1], mx[1]):
            for z in (mn[2], mx[2]):
                t = _dot(_sub((x, y, z), origin), direction)
                lo, hi = min(lo, t), max(hi, t)
    return lo, hi


def _seam(face_pocket, face_pilot):
    """Геометрия шва. Возвращает dict или (None, причина)."""
    n1, p1 = _face_normal(face_pocket)   # карманная пласть A
    n2, p2 = _face_normal(face_pilot)    # пласть B под пилоты
    d = _cross(n1, n2)
    dl = math.sqrt(_dot(d, d))
    if dl < 0.09:
        return None, "Грани почти параллельны — шов не определяется"
    axis = _mul(d, 1.0 / dl)
    # точка на линии пересечения плоскостей
    d1 = _dot(n1, p1)
    d2 = _dot(n2, p2)
    p0 = _mul(_cross(_sub(_mul(n2, d1), _mul(n1, d2)), d), 1.0 / (dl * dl))

    body_a = face_pocket.body
    body_b = face_pilot.body
    if body_a == body_b:
        return None, "Обе грани на одном теле — нужны две детали"
    a_lo, a_hi = _body_interval(body_a, p0, axis)
    b_lo, b_hi = _body_interval(body_b, p0, axis)
    lo, hi = max(a_lo, b_lo), min(a_hi, b_hi)
    if hi - lo < 2 * CAB_MIN_EDGE + 5:
        return None, f"Перекрытие деталей вдоль шва {hi - lo:.0f} мм — мало"

    # направление «от кромки вглубь A» = наружная нормаль B (от B к A);
    # проверка: центр тела A должен лежать с этой стороны
    ca = _mul(_add(_v(body_a.boundingBox.minPoint),
                   _v(body_a.boundingBox.maxPoint)), 5.0)  # (min+max)/2 *10
    if _dot(_sub(ca, p0), n2) < 0:
        n2 = _mul(n2, -1.0)
    cb = _mul(_add(_v(body_b.boundingBox.minPoint),
                   _v(body_b.boundingBox.maxPoint)), 5.0)
    if _dot(_sub(cb, p0), n1) < 0:
        n1 = _mul(n1, -1.0)
    # n1 теперь смотрит от карманной пласти в сторону тела B?  Нет:
    # нам нужен вектор от F1 в сторону, где стоит тело B ЗА пластью?
    # Пилот: ось винта на 5 мм от плоскости F1 в сторону тела A.
    to_a = _mul(n1, -1.0) if _dot(_sub(ca, p1), n1) < 0 else n1
    # надёжнее: вектор от плоскости F1 к центру тела A
    s = _dot(_sub(ca, p1), n1)
    to_a = n1 if s > 0 else _mul(n1, -1.0)

    return dict(axis=axis, p0=p0, lo=lo, hi=hi, into_a=n2, to_a=to_a,
                body_a=body_a, body_b=body_b), None


def _positions(lo, hi, edge, step, count):
    a, b = lo + edge, hi - edge
    if b <= a:
        return [(lo + hi) / 2.0]
    n = count if count and count > 0 else \
        max(2, int(math.ceil((b - a) / step)) + 1)
    if n == 1:
        return [(a + b) / 2.0]
    return [a + (b - a) * k / (n - 1) for k in range(n)]


# ------------------------------------------------------------------ build
def _cut_circles(design, face, body, points_mm, dia, depth, tag):
    """Эскиз на плоскости выбранной грани, круги по мировым точкам,
    вырез в тело на глубину; направление подбирается по факту (объём)."""
    root = design.rootComponent
    pi = root.constructionPlanes.createInput()
    pi.setByOffset(face, adsk.core.ValueInput.createByReal(0))
    pl = root.constructionPlanes.add(pi)
    pl.isLightBulbOn = False
    sk = root.sketches.add(pl)
    sk.name = f"cabineo_{tag}"
    for pt in points_mm:
        ctr = sk.modelToSketchSpace(adsk.core.Point3D.create(
            pt[0] * MM, pt[1] * MM, pt[2] * MM))
        ctr.z = 0
        sk.sketchCurves.sketchCircles.addByCenterRadius(ctr, dia / 2.0 * MM)
    profs = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        profs.add(sk.profiles.item(i))

    vol0 = body.volume
    ext = root.features.extrudeFeatures

    def try_cut(dist):
        ei = ext.createInput(
            profs, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ei.setDistanceExtent(False,
                             adsk.core.ValueInput.createByReal(dist * MM))
        ei.participantBodies = [body]
        try:
            return ext.add(ei)
        except Exception:
            return None

    feat = try_cut(-depth)
    if feat is None or abs(body.volume - vol0) < 1e-9:
        if feat:
            try:
                feat.deleteMe()
            except Exception:
                pass
        feat = try_cut(depth)
    sk.isVisible = False
    changed = abs(body.volume - vol0) > 1e-9
    return changed


# ------------------------------------------------------------------ dialog
def _build_dialog(cmd):
    inp = cmd.commandInputs
    R = adsk.core.ValueInput.createByReal

    s1 = inp.addSelectionInput(
        "fpocket", "Пласть под шляпки (карманы)",
        "Плоская пласть детали, в которую фрезеруются карманы Cabineo")
    s1.addSelectionFilter("PlanarFaces")
    s1.setSelectionLimits(1, 1)

    s2 = inp.addSelectionInput(
        "fpilot", "Пласть под пилоты",
        "Пласть второй детали, к которой примыкает торец первой")
    s2.addSelectionFilter("PlanarFaces")
    s2.setSelectionLimits(1, 1)

    inp.addIntegerSpinnerCommandInput("cnt", "Cabineo на шов (0 = авто)",
                                      0, 20, 1, 0)
    inp.addValueInput("edge", "Отступ крайних от концов шва", "mm", R(5.0))
    inp.addValueInput("step", "Шаг для авто (<=300)", "mm", R(25.0))

    box = inp.addTextBoxCommandInput("infoBox", "Расчёт", "", 4, True)
    box.isFullWidth = True


def _refresh_info(cmd):
    box = cmd.commandInputs.itemById("infoBox")
    if not box:
        return
    try:
        inp = cmd.commandInputs
        s1 = inp.itemById("fpocket")
        s2 = inp.itemById("fpilot")
        if s1.selectionCount < 1 or s2.selectionCount < 1:
            box.text = "Выберите обе пласти"
            return
        seam, err = _seam(s1.selection(0).entity, s2.selection(0).entity)
        if err:
            box.text = "! " + err
            return
        pos = _positions(seam["lo"], seam["hi"], _mm(inp.itemById("edge")),
                         _mm(inp.itemById("step")),
                         int(inp.itemById("cnt").value))
        box.text = (f"Шов: перекрытие {seam['hi'] - seam['lo']:.0f} мм, "
                    f"коннекторов: {len(pos)}\n"
                    f"Карман 3×Ø15×11 (центры 3.6/14.8/26 от кромки), "
                    f"пилот Ø5×8 на оси 5 мм")
    except Exception:
        box.text = "…"


# ---------------------------------------------------------------- handlers
class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id == "infoBox":
                return
            _refresh_info(args.firingEvent.sender)
        except Exception:
            pass


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            _build_dialog(cmd)
            on_exec = ExecHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
            on_change = InputChangedHandler()
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)
        except Exception:
            _fail("CreatedHandler")


class ExecHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            cmd = args.firingEvent.sender
            inp = cmd.commandInputs
            design = adsk.fusion.Design.cast(_app.activeProduct)
            f1 = inp.itemById("fpocket").selection(0).entity
            f2 = inp.itemById("fpilot").selection(0).entity
            seam, err = _seam(f1, f2)
            if err:
                _ui.messageBox("! " + err, CMD_NAME)
                return
            pos = _positions(seam["lo"], seam["hi"],
                             _mm(inp.itemById("edge")),
                             _mm(inp.itemById("step")),
                             int(inp.itemById("cnt").value))

            axis, p0 = seam["axis"], seam["p0"]
            into_a, to_a = seam["into_a"], seam["to_a"]
            pocket_pts = []
            pilot_pts = []
            for t in pos:
                base = _add(p0, _mul(axis, t))
                for c in CAB_CUP_CENTERS:
                    pocket_pts.append(_add(base, _mul(into_a, c)))
                pilot_pts.append(_add(base, _mul(to_a, CAB_AXIS_X)))

            ok1 = _cut_circles(design, f1, seam["body_a"], pocket_pts,
                               CAB_CUP_D, CAB_POCKET_DEPTH, "pockets")
            ok2 = _cut_circles(design, f2, seam["body_b"], pilot_pts,
                               CAB_PILOT_D, CAB_PILOT_DEPTH, "pilots")

            bad = "ТЕЛО НЕ ИЗМЕНИЛОСЬ (baseFeature/импорт? резать нельзя)"
            msg = (f"Коннекторов: {len(pos)}\n"
                   f"Карманы: {'ок' if ok1 else bad}\n"
                   f"Пилоты: {'ок' if ok2 else bad}")
            _ui.messageBox(msg, CMD_NAME)
        except Exception:
            _fail("ExecHandler")


# ---------------------------------------------------------------- run/stop
def run(context):
    global _app, _ui
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface

        defs = _ui.commandDefinitions
        existing = defs.itemById(CMD_ID)
        if existing:
            existing.deleteMe()
        icons = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "resources")
        cmd_def = defs.addButtonDefinition(CMD_ID, CMD_NAME, CMD_DESC, icons)

        on_created = CreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        ws = _ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        if panel:
            old = panel.controls.itemById(CMD_ID)
            if old:
                old.deleteMe()
            panel.controls.addCommand(cmd_def)
    except Exception:
        _fail("run")


def stop(context):
    try:
        ws = _ui.workspaces.itemById(WORKSPACE_ID)
        panel = ws.toolbarPanels.itemById(PANEL_ID)
        ctrl = panel.controls.itemById(CMD_ID) if panel else None
        if ctrl:
            ctrl.deleteMe()
        cmd_def = _ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        _fail("stop")

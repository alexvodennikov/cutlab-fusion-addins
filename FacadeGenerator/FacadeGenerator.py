# -*- coding: utf-8 -*-
"""FacadeGenerator — Fusion add-in: генератор мебельных фасадов.

Петля по умолчанию: Blum CLIP top BLUMOTION 110°, EXPANDO;
ответная планка прямая EXPANDO. Размеры сверловки — из официального
PDF Blum (см. facade_core.py).

Режимы:
- выбраны боковины корпуса (1–2 тела) — размеры и позиция берутся с них,
  сверловка планок режется прямо в боковинах;
- ничего не выбрано — размеры из полей, сверловка планок отдаётся
  телами-свёрлами.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

# Stop -> Run перечитывает только этот файл; наши модули остаются в кэше
# питона Fusion со старым кодом — сбрасываем их принудительно
for _m in ("facade_core", "facadegen_build"):
    if _m in sys.modules:
        del sys.modules[_m]

from facade_core import FacadeParams, compute, auto_hinge_count
from facadegen_build import build_facades

_app = None
_ui = None
_handlers = []

CMD_ID = "facadeGeneratorCmd"
CMD_NAME = "Генератор фасадов"
CMD_DESC = "Фасады с присадкой под петли Blum CLIP top (EXPANDO)"
PANEL_ID = "SolidCreatePanel"
WORKSPACE_ID = "FusionSolidEnvironment"

BAND_OPTIONS = [("Без канта (чистый размер)", 0.0),
                ("Кант 0.6 мм", 0.6),
                ("Кант 1.0 мм", 1.0),
                ("Кант 2.0 мм", 2.0)]


def _fail(where):
    if _ui:
        _ui.messageBox(f"{where}:\n{traceback.format_exc()}")


def _mm(inp):
    return inp.value * 10.0


# ------------------------------------------------------------------ dialog
def _build_dialog(cmd):
    inp = cmd.commandInputs
    R = adsk.core.ValueInput.createByReal

    def val(g, idn, name, mm):
        return g.addValueInput(idn, name, "mm", R(mm / 10.0))

    sel = inp.addSelectionInput(
        "walls", "Боковины корпуса",
        "Выберите тела боковин (1–2); пусто — размеры из полей")
    sel.addSelectionFilter("Bodies")
    sel.setSelectionLimits(0, 2)

    g1 = inp.addGroupCommandInput("gCab", "Корпус").children
    val(g1, "cw", "Ширина корпуса (снаружи)", 600)
    val(g1, "ch", "Высота боковины", 720)
    val(g1, "wt", "Толщина боковины", 18)
    val(g1, "rev", "Отступ фасада от края боковины", 2)

    g2 = inp.addGroupCommandInput("gFac", "Фасады").children
    nd = g2.addDropDownCommandInput(
        "nfac", "Количество",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    nd.listItems.add("Один фасад", True)
    nd.listItems.add("Два симметричных", False)
    nd.listItems.add("Два разной ширины", False)
    val(g2, "lw", "Ширина левого (для «двух разных»)", 300)
    val(g2, "fth", "Толщина фасада", 18)
    val(g2, "gap", "Зазор фасада (между/верх/низ)", 3)
    val(g2, "offt", "Отступ зоны сверху (ящик над дверью)", 0)
    val(g2, "offb", "Отступ зоны снизу (ящик под дверью)", 0)

    g3 = inp.addGroupCommandInput("gBand", "Кант").children
    bd = g3.addDropDownCommandInput(
        "band", "Кант", adsk.core.DropDownStyles.TextListDropDownStyle)
    for i, (name, _) in enumerate(BAND_OPTIONS):
        bd.listItems.add(name, i == 0)
    g3.addBoolValueInput("r2", "Скругление углов R2 (без канта)",
                         True, "", False)

    g4 = inp.addGroupCommandInput("gHinge", "Петли Blum CLIP top").children
    hs = g4.addDropDownCommandInput(
        "hside", "Сторона петель (один фасад)",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    hs.listItems.add("Слева", True)
    hs.listItems.add("Справа", False)
    g4.addIntegerSpinnerCommandInput("nh", "Петель (0 = авто)", 0, 6, 1, 0)
    val(g4, "ho", "Ось крайней чашки от торца", 100)
    val(g4, "tb", "Отступ сверловки TB (0 = авто)", 0)

    box = inp.addTextBoxCommandInput("infoBox", "Расчёт", "", 4, True)
    box.isFullWidth = True
    _refresh_info(cmd)


def _read_params(cmd):
    inp = cmd.commandInputs
    band = BAND_OPTIONS[inp.itemById("band").selectedItem.index][1]
    nfac_idx = inp.itemById("nfac").selectedItem.index
    return FacadeParams(
        cab_width=_mm(inp.itemById("cw")),
        cab_height=_mm(inp.itemById("ch")),
        wall_thickness=_mm(inp.itemById("wt")),
        reveal=_mm(inp.itemById("rev")),
        tb_override=_mm(inp.itemById("tb")),
        thickness=_mm(inp.itemById("fth")),
        n_facades=1 if nfac_idx == 0 else 2,
        left_width=_mm(inp.itemById("lw")) if nfac_idx == 2 else 0.0,
        mid_gap=_mm(inp.itemById("gap")),
        offset_top=_mm(inp.itemById("offt")),
        offset_bottom=_mm(inp.itemById("offb")),
        top_gap=_mm(inp.itemById("gap")),
        bottom_gap=_mm(inp.itemById("gap")),
        band=band,
        corner_r=2.0 if (inp.itemById("r2").value and band <= 0) else 0.0,
        n_hinges=int(inp.itemById("nh").value),
        hinge_edge_offset=_mm(inp.itemById("ho")),
        hinge_side=("right"
                    if inp.itemById("hside").selectedItem.index == 1
                    else "left"),
    )


def _walls_info(cmd):
    """Выбранные тела боковин + габарит (мм): (bodies, origin, w, h, wt)."""
    sel = cmd.commandInputs.itemById("walls")
    if not sel or sel.selectionCount == 0:
        return None
    bodies = [sel.selection(i).entity for i in range(sel.selectionCount)]
    mn = [1e18, 1e18, 1e18]
    mx = [-1e18, -1e18, -1e18]
    wt = 1e18
    for b in bodies:
        bb = b.boundingBox
        pts = (bb.minPoint, bb.maxPoint)
        for k, get in enumerate((lambda p: p.x, lambda p: p.y,
                                 lambda p: p.z)):
            mn[k] = min(mn[k], get(pts[0]) * 10.0)
            mx[k] = max(mx[k], get(pts[1]) * 10.0)
        wt = min(wt, (bb.maxPoint.x - bb.minPoint.x) * 10.0)
    origin = (mn[0], mn[1], mn[2])
    return bodies, origin, mx[0] - mn[0], mx[2] - mn[2], wt


def _apply_walls(cmd, p):
    """Если выбраны боковины — переопределяем габариты из них."""
    info = _walls_info(cmd)
    if info is None:
        return None, (0.0, 0.0, 0.0)
    bodies, origin, w, h, wt = info
    p.cab_width = w
    p.cab_height = h
    p.wall_thickness = wt
    return bodies, origin


def _refresh_info(cmd):
    box = cmd.commandInputs.itemById("infoBox")
    if not box:
        return
    try:
        p = _read_params(cmd)
        _apply_walls(cmd, p)
        lay = compute(p)
        f0 = lay["facades"][0]
        sizes = "  +  ".join(
            f"{f.detail_width:.1f}×{f.detail_height:.1f}"
            for f in lay["facades"])
        box.text = (
            f"Наложение FA = {lay['fa']:.1f} мм   TB = {lay['tb']:.1f} мм\n"
            f"Петель на фасад: {len(f0.hinge_z)}\n"
            f"Деталь(и): {sizes} × {p.thickness:.0f} мм\n"
            + ("; ".join(lay["warnings"]) if lay["warnings"] else ""))
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
            p = _read_params(cmd)
            wall_bodies, origin = _apply_walls(cmd, p)
            lay = compute(p)

            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _app.documents.add(
                    adsk.core.DocumentTypes.FusionDesignDocumentType)
                design = adsk.fusion.Design.cast(_app.activeProduct)

            log = build_facades(design, p, lay, origin=origin,
                                wall_bodies=wall_bodies)
            msg = "\n".join(log)
            for w in lay["warnings"]:
                msg += f"\n! {w}"
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
        icons = os.path.join(_dir, "resources")
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

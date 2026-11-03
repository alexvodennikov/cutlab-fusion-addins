# -*- coding: utf-8 -*-
"""BoxGenerator — Fusion add-in: короба на Lamello Cabineo 8.

Пять панелей (верх, низ, боковины, врезной задник заподлицо). Углы —
прямые детали с Cabineo (схема A/B) или взаимная гребёнка как в
CabinetGenerator. Шляпки Cabineo наружу или внутрь. Съёмный задник:
четыре упора на задних торцах панелей с магнитами.

Фрезеровка Cabineo 8 — официальный лист Lamello (Bund aufliegend,
фреза >=Ø10): карман 3×Ø15 глубиной 11 (центры 3.6/14.8/26 от кромки),
пилот Ø5×8 (X = 8) на оси 5 мм от карманной пласти.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

for _m in ("box_core", "boxgen_build"):
    if _m in sys.modules:
        del sys.modules[_m]

from box_core import BoxParams, compute, cutlist_text
from boxgen_build import build_box

_app = None
_ui = None
_handlers = []

CMD_ID = "boxGeneratorCmd"
CMD_NAME = "Генератор коробов (Cabineo)"
CMD_DESC = "Короб из листа на Lamello Cabineo 8 под 3-осевой ЧПУ"
PANEL_ID = "SolidCreatePanel"
WORKSPACE_ID = "FusionSolidEnvironment"


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

    g1 = inp.addGroupCommandInput("gDims", "Габариты (наружные)").children
    val(g1, "w", "Ширина", 800)
    val(g1, "h", "Высота", 426)
    val(g1, "d", "Глубина", 748)
    val(g1, "mt", "Толщина плиты", 18)
    val(g1, "px", "Позиция X", 0)
    val(g1, "py", "Позиция Y", 0)
    val(g1, "pz", "Позиция Z", 0)

    g2 = inp.addGroupCommandInput("gJoint", "Углы").children
    jd = g2.addDropDownCommandInput(
        "joint", "Соединение",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    jd.listItems.add("Прямые детали + Cabineo", True)
    jd.listItems.add("Шип-паз (гребёнка, как CabinetGenerator)", False)
    sd = g2.addDropDownCommandInput(
        "scheme", "Схема (для прямых)",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    sd.listItems.add("A: верх и низ во всю ширину", True)
    sd.listItems.add("B: боковины во всю высоту", False)
    g2.addIntegerSpinnerCommandInput("nt", "Шипов на угол (гребёнка)",
                                     1, 12, 1, 3)
    val(g2, "cl", "Зазор посадки гребёнки", 0.1)

    g3 = inp.addGroupCommandInput("gCab", "Cabineo 8").children
    fd = g3.addDropDownCommandInput(
        "cface", "Шляпки",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    fd.listItems.add("Наружу (скрытый изнутри крепёж)", True)
    fd.listItems.add("Внутрь короба", False)
    g3.addBoolValueInput("csides", "Cabineo на угловых швах", True, "", True)
    g3.addIntegerSpinnerCommandInput(
        "ncs", "На угловой шов (0 = авто по шагу)", 0, 12, 1, 0)
    g3.addBoolValueInput("cback", "Cabineo на заднике", True, "", True)
    g3.addIntegerSpinnerCommandInput(
        "ncb", "На каждый шов задника (0 = авто)", 0, 12, 1, 0)
    val(g3, "cedge", "Отступ крайних от концов шва", 50)
    val(g3, "cstep", "Шаг для авто (<=300)", 250)

    g4 = inp.addGroupCommandInput("gBack", "Съёмный задник").children
    g4.addBoolValueInput("rback", "Задник съёмный (упоры + магниты)",
                         True, "", False)
    val(g4, "magd", "Магнит Ø", 18)
    val(g4, "magt", "Магнит толщина", 5)
    val(g4, "stl", "Упор: длина", 100)
    val(g4, "stw", "Упор: ширина (свес в проём)", 60)

    box = inp.addTextBoxCommandInput("infoBox", "Расчёт", "", 6, True)
    box.isFullWidth = True
    _refresh_info(cmd)


def _read_params(cmd):
    inp = cmd.commandInputs
    return BoxParams(
        width=_mm(inp.itemById("w")),
        height=_mm(inp.itemById("h")),
        depth=_mm(inp.itemById("d")),
        material_t=_mm(inp.itemById("mt")),
        joint="tabs" if inp.itemById("joint").selectedItem.index == 1
              else "straight",
        scheme="B" if inp.itemById("scheme").selectedItem.index == 1 else "A",
        n_tabs=int(inp.itemById("nt").value),
        tab_clearance=_mm(inp.itemById("cl")),
        cab_face="inside" if inp.itemById("cface").selectedItem.index == 1
                 else "outside",
        cab_sides=inp.itemById("csides").value,
        cab_back=inp.itemById("cback").value,
        cab_count_side=int(inp.itemById("ncs").value),
        cab_count_back=int(inp.itemById("ncb").value),
        cab_edge=_mm(inp.itemById("cedge")),
        cab_step=_mm(inp.itemById("cstep")),
        removable_back=inp.itemById("rback").value,
        magnet_d=_mm(inp.itemById("magd")),
        magnet_t=_mm(inp.itemById("magt")),
        stop_len=_mm(inp.itemById("stl")),
        stop_w=_mm(inp.itemById("stw")),
        origin_x=_mm(inp.itemById("px")),
        origin_y=_mm(inp.itemById("py")),
        origin_z=_mm(inp.itemById("pz")),
    )


def _refresh_info(cmd):
    box = cmd.commandInputs.itemById("infoBox")
    if not box:
        return
    try:
        p = _read_params(cmd)
        res = compute(p)
        box.text = cutlist_text(p, res)
    except Exception:
        box.text = "…"


# ---------------------------------------------------------------- handlers
class InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            if args.input.id == "infoBox":
                return
            inp = args.firingEvent.sender.commandInputs
            is_tabs = inp.itemById("joint").selectedItem.index == 1
            inp.itemById("scheme").isEnabled = not is_tabs
            inp.itemById("nt").isEnabled = is_tabs
            inp.itemById("cl").isEnabled = is_tabs
            inp.itemById("csides").isEnabled = not is_tabs
            rb = inp.itemById("rback").value
            inp.itemById("cback").isEnabled = not rb
            for idn in ("magd", "magt", "stl", "stw"):
                inp.itemById(idn).isEnabled = rb
            _refresh_info(args.firingEvent.sender)
        except Exception:
            pass


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            cmd.setDialogInitialSize(400, 640)
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
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _app.documents.add(
                    adsk.core.DocumentTypes.FusionDesignDocumentType)
                design = adsk.fusion.Design.cast(_app.activeProduct)
            p = _read_params(cmd)
            res = compute(p)
            log = build_box(design, p, res)
            msg = cutlist_text(p, res) + "\n\n" + "\n".join(log)
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

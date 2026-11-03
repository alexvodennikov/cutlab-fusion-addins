# -*- coding: utf-8 -*-
"""CabinetGenerator — Fusion add-in: параметрические корпуса из листа
на сквозных шип-пазах (3-осевой ЧПУ).

- Каждая деталь — отдельный компонент (для Arrange), корпус — свой
  компонент; корпусов в документе сколько угодно, они не конфликтуют.
- Толщина материала/задника: «Глобальная» — берётся из параметров
  документа cg_material_t / cg_back_t (создаются при первом запуске,
  общие для всех корпусов), «Локальная» — из полей диалога только для
  этого корпуса.
- Пилоты Ø3 сквозь пальцы горизонтов и задника; заходные скругления
  углов шипов; зазор посадки в пазах. Dogbones — потом, вручную.
"""

import os
import sys
import traceback

import adsk.core
import adsk.fusion

_dir = os.path.dirname(os.path.abspath(__file__))
if _dir not in sys.path:
    sys.path.insert(0, _dir)

# Stop -> Run перечитывает только этот файл; сбрасываем кэш своих модулей
for _m in ("cabinet_core", "cabinetgen_build"):
    if _m in sys.modules:
        del sys.modules[_m]

from cabinet_core import CabinetParams, compute
from cabinetgen_build import build_cabinet

_app = None
_ui = None
_handlers = []

CMD_ID = "cabinetGeneratorCmd"
CMD_NAME = "Генератор корпусов"
CMD_DESC = "Корпус из листа на шип-пазах под 3-осевой ЧПУ"
PANEL_ID = "SolidCreatePanel"
WORKSPACE_ID = "FusionSolidEnvironment"


def _fail(where):
    if _ui:
        _ui.messageBox(f"{where}:\n{traceback.format_exc()}")


def _mm(inp):
    return inp.value * 10.0


def _parse_heights(s):
    """'200, 400' -> [200.0, 400.0]; мусор игнорируется."""
    out = []
    for tok in (s or "").replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _ensure_global_param(design, name, value_mm, comment):
    """Вернуть значение глобального параметра (создать при отсутствии)."""
    up = design.userParameters
    ex = up.itemByName(name)
    if ex:
        return ex.value * 10.0          # значение параметра главнее поля
    up.add(name, adsk.core.ValueInput.createByString(f"{value_mm} mm"),
           "mm", comment)
    return value_mm


# ------------------------------------------------------------------ dialog
def _build_dialog(cmd):
    inp = cmd.commandInputs
    R = adsk.core.ValueInput.createByReal

    def val(g, idn, name, mm):
        return g.addValueInput(idn, name, "mm", R(mm / 10.0))

    g1 = inp.addGroupCommandInput("gDims", "Габариты (наружные)").children
    val(g1, "w", "Ширина", 600)
    val(g1, "h", "Высота", 720)
    val(g1, "d", "Глубина", 500)
    val(g1, "px", "Позиция X", 0)
    val(g1, "py", "Позиция Y", 0)
    val(g1, "pz", "Позиция Z", 0)

    g2 = inp.addGroupCommandInput("gMat", "Материал").children
    md = g2.addDropDownCommandInput(
        "mmode", "Толщина корпуса",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    md.listItems.add("Глобальная (cg_material_t)", True)
    md.listItems.add("Локальная (для этого корпуса)", False)
    val(g2, "mt", "Толщина материала", 18)
    g2.addBoolValueInput("hasback", "Задник", True, "", True)
    val(g2, "bt", "Толщина задника", 9)

    gs = inp.addGroupCommandInput("gShelf", "Полки").children
    gs.addIntegerSpinnerCommandInput("nsh", "Полок", 0, 8, 1, 0)
    st = gs.addDropDownCommandInput(
        "shtype", "Тип полок",
        adsk.core.DropDownStyles.TextListDropDownStyle)
    st.listItems.add("Стационарные (шип-паз)", True)
    st.listItems.add("Съёмные (полкодержатели Ø5)", False)
    gs.addStringValueInput(
        "shz", "Высоты полок, мм (пусто = равномерно)", "")
    gs.addIntegerSpinnerCommandInput(
        "shadj", "Регулировка ±N позиций ×32", 0, 5, 1, 0)

    g3 = inp.addGroupCommandInput("gJoint", "Шип-паз").children
    g3.addIntegerSpinnerCommandInput("nt", "Шипов на угол", 1, 12, 1, 3)
    g3.addIntegerSpinnerCommandInput("nb", "Шипов задника по высоте",
                                     1, 12, 1, 3)
    val(g3, "pd", "Пилот под шуруп Ø", 3)
    val(g3, "er", "Заходное скругление шипов R", 1)
    val(g3, "cl", "Зазор посадки (на сторону)", 0.1)

    box = inp.addTextBoxCommandInput("infoBox", "Расчёт", "", 3, True)
    box.isFullWidth = True
    _refresh_info(cmd)


def _read_params(cmd, design=None):
    inp = cmd.commandInputs
    p = CabinetParams(
        width=_mm(inp.itemById("w")),
        height=_mm(inp.itemById("h")),
        depth=_mm(inp.itemById("d")),
        material_t=_mm(inp.itemById("mt")),
        material_global=inp.itemById("mmode").selectedItem.index == 0,
        has_back=inp.itemById("hasback").value,
        back_t=_mm(inp.itemById("bt")),
        n_tabs=int(inp.itemById("nt").value),
        n_back_tabs=int(inp.itemById("nb").value),
        pilot_d=_mm(inp.itemById("pd")),
        ease_r=_mm(inp.itemById("er")),
        clearance=_mm(inp.itemById("cl")),
        origin_x=_mm(inp.itemById("px")),
        origin_y=_mm(inp.itemById("py")),
        origin_z=_mm(inp.itemById("pz")),
        n_shelves=int(inp.itemById("nsh").value),
        shelf_type=("adjustable"
                    if inp.itemById("shtype").selectedItem.index == 1
                    else "fixed"),
        shelf_z=_parse_heights(inp.itemById("shz").value),
        shelf_adjust_steps=int(inp.itemById("shadj").value),
    )
    if p.material_global and design is not None:
        p.material_t = _ensure_global_param(
            design, "cg_material_t", p.material_t,
            "Толщина корпусного материала (все корпуса)")
        p.back_t = _ensure_global_param(
            design, "cg_back_t", p.back_t,
            "Толщина задника (все корпуса)")
    return p


def _refresh_info(cmd):
    box = cmd.commandInputs.itemById("infoBox")
    if not box:
        return
    try:
        design = adsk.fusion.Design.cast(_app.activeProduct)
        p = _read_params(cmd, None)   # без создания параметров
        if p.material_global and design:
            up = design.userParameters
            ex = up.itemByName("cg_material_t")
            if ex:
                p.material_t = ex.value * 10.0
            exb = up.itemByName("cg_back_t")
            if exb:
                p.back_t = exb.value * 10.0
        seg = p.depth / (2 * p.n_tabs + 1)
        box.text = (
            f"Толщина: {p.material_t:.1f} мм "
            f"({'глобальная' if p.material_global else 'локальная'}), "
            f"задник {p.back_t:.1f} мм\n"
            f"Сегмент гребёнки по глубине: {seg:.1f} мм\n"
            f"Деталей: {5 if p.has_back else 4}")
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
            design = adsk.fusion.Design.cast(_app.activeProduct)
            if not design:
                _app.documents.add(
                    adsk.core.DocumentTypes.FusionDesignDocumentType)
                design = adsk.fusion.Design.cast(_app.activeProduct)

            p = _read_params(cmd, design)
            lay = compute(p)
            log = build_cabinet(design, p, lay)
            msg = "\n".join(log)
            for w in lay["warnings"]:
                msg += f"\n! {w}"
            if p.material_global:
                msg += ("\nТолщины взяты из cg_material_t / cg_back_t "
                        "(Modify -> Change Parameters)")
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

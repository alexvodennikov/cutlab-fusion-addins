# -*- coding: utf-8 -*-
"""Add-in Fusion 360: генератор ящиков REJS Ultrabox.

Создаёт кнопку «Ящик Ultrabox» на панели SOLID > Create.

Режим «в корпус»: выберите два тела боковин корпуса — внутренняя ширина
LW, толщина стенок, длина NL и позиция возьмутся с корпуса; присадка
режется прямо в боковинах. Поле «Ящиков в колонне» ставит несколько
ящиков друг над другом.
"""
import os
import sys
import traceback

import adsk.core
import adsk.fusion

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

# при повторном запуске add-in перезагружаем модули
for _m in ('ultrabox_core', 'fusion_build'):
    if _m in sys.modules:
        del sys.modules[_m]
import ultrabox_core as core
import fusion_build

CMD_ID = 'CutLabUltraboxRejs'
_handlers = []


def _ui():
    app = adsk.core.Application.get()
    return app, app.userInterface


# ---------- корпус из выбранных боковин ----------

def _cab_info(inputs):
    """Из выбранных тел боковин: (bodies, origin(x,y,z), lw, side_t,
    depth, height) в мм или None."""
    sel = inputs.itemById('cab_sel')
    if not sel or sel.selectionCount < 2:
        return None
    bodies = [sel.selection(i).entity for i in range(sel.selectionCount)]
    boxes = []
    for b in bodies:
        bb = b.boundingBox
        boxes.append((bb.minPoint.x * 10, bb.maxPoint.x * 10,
                      bb.minPoint.y * 10, bb.maxPoint.y * 10,
                      bb.minPoint.z * 10, bb.maxPoint.z * 10))
    boxes.sort(key=lambda t: t[0])
    left, right = boxes[0], boxes[-1]
    lw = right[0] - left[1]                      # между внутренними плоскостями
    side_t = min(left[1] - left[0], right[1] - right[0])
    if lw <= 50:
        return None
    ox = left[1]                                 # левая внутренняя плоскость
    oy = min(left[2], right[2])                  # передний торец
    oz = min(left[4], right[4])                  # низ боковин
    depth = max(left[3], right[3]) - oy
    height = max(left[5], right[5]) - oz
    return bodies, (ox, oy, oz), lw, side_t, depth, height


def _auto_nl(depth_mm, back_t=9.0):
    """Максимальный каталожный NL, влезающий в глубину (минус задник и запас)."""
    fit = [nl for nl in core.LENGTHS
           if nl + core.DEPTH_EXTRA_STD <= depth_mm - back_t]
    return fit[-1] if fit else core.LENGTHS[0]


# ---------- построение сводки для окна диалога ----------

def _cfg_from_inputs(inputs):
    def val(id_):
        return inputs.itemById(id_).value

    def mm(id_):
        return inputs.itemById(id_).value * 10.0  # внутренние см -> мм

    return dict(
        h=int(inputs.itemById('h').selectedItem.name),
        nl=int(inputs.itemById('nl').selectedItem.name),
        lw=mm('lw'),
        inner=inputs.itemById('kind').selectedItem.index == 1,
        push_open=val('push_open'),
        sync=val('sync'),
        bottom_t=mm('bottom_t'),
        back_t=mm('back_t'),
        side_t=mm('side_t'),
        facade_t=mm('facade_t'),
        facade_w=mm('facade_w'),
        facade_h=mm('facade_h'),
        facade_below=mm('facade_below'),
        facade_gap=mm('facade_gap'),
        facade_drill=val('facade_drill'),
        cab_drill={0: 'none', 1: 'bodies', 2: 'cut'}[inputs.itemById('cab_drill').selectedItem.index],
    )


def _pitch_mm(inputs, res):
    """Шаг колонны по Z: поле или авто (фасад+3 / E_min+10)."""
    v = inputs.itemById('pitch').value * 10.0
    if v > 0.5:
        return v
    if res.get('facade'):
        return res['facade']['hgt'] + 3.0
    return res['e_min'] + 10.0


def _update_summary(inputs):
    box = inputs.itemById('summary')
    try:
        cfg = _cfg_from_inputs(inputs)
        res = core.compute(cfg)
        lines = ['Комплект: %s' % res['articles']['runner_set']]
        for k, v in res['articles'].items():
            if k != 'runner_set':
                lines.append('+ %s' % v)
        lines.append('Мин. проём: E=%d мм, глубина %d мм' % (res['e_min'], res['depth_min']))
        info = _cab_info(inputs)
        n = int(inputs.itemById('ndrawers').value)
        if info:
            _, origin, lw, side_t, depth, height = info
            lines.append('Корпус: LW=%.1f, стенка %.0f, глубина %.0f, высота %.0f'
                         % (lw, side_t, depth, height))
            if n > 1:
                pitch = _pitch_mm(inputs, res)
                total = inputs.itemById('mount_z').value * 10.0 + \
                    (n - 1) * pitch + res['e_min']
                lines.append('Колонна: %d шт, шаг %.0f, занято %.0f мм'
                             % (n, pitch, total))
                if total > height - 2 * side_t:
                    lines.append('! колонна выше проёма (~%.0f)' % (height - 2 * side_t))
        for p in res['panels']:
            lines.append('%s: %.0f x %.0f x %.0f' % (p['name'], p['w'], p['l'], p['t']))
        lines += ['! ' + w for w in res['warnings']]
        box.text = '\n'.join(lines)
        box.numRows = min(12, len(lines) + 1)
    except Exception as e:
        box.text = 'Ошибка: %s' % e


class _CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            cmd.setDialogInitialSize(380, 640)

            sel = inputs.addSelectionInput(
                'cab_sel', 'Корпус (2 боковины)',
                'Выберите тела боковин корпуса: LW, толщина, NL и позиция '
                'возьмутся автоматически')
            sel.addSelectionFilter('Bodies')
            sel.setSelectionLimits(0, 2)

            dd = inputs.addDropDownCommandInput('h', 'Высота боковины H',
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            for h in core.HEIGHTS:
                dd.listItems.add(str(h), h == 167)
            dd = inputs.addDropDownCommandInput('nl', 'Номинальная длина NL',
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            for nl in core.LENGTHS:
                dd.listItems.add(str(nl), nl == 500)
            inputs.addValueInput('lw', 'Внутр. ширина корпуса LW', 'mm',
                                 adsk.core.ValueInput.createByReal(56.4))
            inputs.addValueInput('side_t', 'Толщина стенок корпуса', 'mm',
                                 adsk.core.ValueInput.createByReal(1.8))
            dd = inputs.addDropDownCommandInput('kind', 'Тип ящика',
                                                adsk.core.DropDownStyles.TextListDropDownStyle)
            dd.listItems.add('Стандартный (с фасадом)', True)
            dd.listItems.add('Внутренний', False)
            inputs.addBoolValueInput('push_open', 'Push-open', True, '', False)
            inputs.addBoolValueInput('sync', 'Синхронизатор', True, '', False)

            g = inputs.addGroupCommandInput('grp_col', 'Установка в корпус')
            gi = g.children
            gi.addIntegerSpinnerCommandInput('ndrawers', 'Ящиков в колонне',
                                             1, 8, 1, 1)
            gi.addValueInput('mount_z', 'Низ направляющей от низа боковины', 'mm',
                             adsk.core.ValueInput.createByReal(2.2))
            gi.addValueInput('pitch', 'Шаг колонны по Z (0 = авто)', 'mm',
                             adsk.core.ValueInput.createByReal(0))

            g = inputs.addGroupCommandInput('grp_mat', 'Листовые детали')
            gi = g.children
            gi.addValueInput('bottom_t', 'Толщина дна', 'mm',
                             adsk.core.ValueInput.createByReal(1.6))
            gi.addValueInput('back_t', 'Толщина задней стенки', 'mm',
                             adsk.core.ValueInput.createByReal(1.6))

            g = inputs.addGroupCommandInput('grp_f', 'Фасад')
            gi = g.children
            gi.addValueInput('facade_t', 'Толщина фасада', 'mm',
                             adsk.core.ValueInput.createByReal(1.8))
            gi.addValueInput('facade_w', 'Ширина (0 = авто)', 'mm',
                             adsk.core.ValueInput.createByReal(0))
            gi.addValueInput('facade_h', 'Высота (0 = авто)', 'mm',
                             adsk.core.ValueInput.createByReal(0))
            gi.addValueInput('facade_below', 'Перекрытие вниз', 'mm',
                             adsk.core.ValueInput.createByReal(2.0))
            gi.addValueInput('facade_gap', 'Зазор фасад-корпус', 'mm',
                             adsk.core.ValueInput.createByReal(0))
            gi.addBoolValueInput('facade_drill', 'Сверловка фасада', True, '', True)

            g = inputs.addGroupCommandInput('grp_c', 'Присадка корпуса')
            gi = g.children
            dd = gi.addDropDownCommandInput('cab_drill', 'Способ',
                                            adsk.core.DropDownStyles.TextListDropDownStyle)
            dd.listItems.add('Нет', False)
            dd.listItems.add('Тела-свёрла (DRILL_*)', True)
            dd.listItems.add('Вырезать в боковинах корпуса', False)

            box = inputs.addTextBoxCommandInput('summary', 'Сводка', '', 8, True)
            box.isFullWidth = True
            _update_summary(inputs)

            on_exec = _ExecuteHandler()
            cmd.execute.add(on_exec)
            _handlers.append(on_exec)
            on_change = _InputChangedHandler()
            cmd.inputChanged.add(on_change)
            _handlers.append(on_change)
        except Exception:
            _ui()[1].messageBox('Ultrabox created failed:\n' + traceback.format_exc())


class _InputChangedHandler(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inputs = args.inputs
            if args.input.id == 'summary':
                return
            if args.input.id == 'cab_sel':
                info = _cab_info(inputs)
                if info:
                    _, origin, lw, side_t, depth, height = info
                    inputs.itemById('lw').value = lw / 10.0
                    inputs.itemById('side_t').value = side_t / 10.0
                    # авто-NL под глубину корпуса
                    nl = _auto_nl(depth, inputs.itemById('back_t').value * 10.0)
                    for li in inputs.itemById('nl').listItems:
                        li.isSelected = (int(li.name) == nl)
                    # присадку по умолчанию режем в выбранный корпус
                    inputs.itemById('cab_drill').listItems.item(2).isSelected = True
            # доступность зависимых полей
            kind_inner = inputs.itemById('kind').selectedItem.index == 1
            inputs.itemById('grp_f').isVisible = not kind_inner
            inputs.itemById('sync').isEnabled = inputs.itemById('push_open').value
            _update_summary(inputs)
        except Exception:
            pass


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args):
        app, ui = _ui()
        try:
            inputs = args.command.commandInputs
            cfg = _cfg_from_inputs(inputs)
            info = _cab_info(inputs)
            n = int(inputs.itemById('ndrawers').value)
            mount_z = inputs.itemById('mount_z').value * 10.0

            do_cut = cfg['cab_drill'] == 'cut'
            targets = list(info[0]) if (do_cut and info) else []
            if do_cut:
                cfg['cab_drill'] = 'none'

            if info:
                _, (ox, oy, oz), lw, side_t, depth, height = info
            else:
                ox = oy = oz = 0.0

            res_probe = core.compute(cfg)
            pitch = _pitch_mm(inputs, res_probe)

            names = []
            warnings = list(res_probe['warnings'])
            for i in range(n):
                off = (ox, oy, oz + mount_z + i * pitch)
                occ, res = fusion_build.build(
                    cfg, offset=off, facade_drill=cfg.get('facade_drill', True))
                names.append(occ.component.name)
                if targets:
                    fusion_build.cut_cabinet(targets, res, offset=off)

            msg = ['Создано: %s' % ', '.join(names),
                   'Комплект: %s' % res_probe['articles']['runner_set']]
            if info:
                msg.append('Корпус: LW=%.1f, NL=%d, ящиков %d, шаг %.0f'
                           % (lw, cfg['nl'], n, pitch))
            msg += ['! ' + w for w in warnings]
            app.activeViewport.fit()
            if warnings:
                ui.messageBox('\n'.join(msg), 'Ultrabox')
        except Exception:
            ui.messageBox('Ultrabox failed:\n' + traceback.format_exc())


def run(context):
    try:
        app, ui = _ui()
        # всегда пересоздаём и кнопку, и определение команды: контрол,
        # оставшийся от прошлой загрузки, указывает на удалённое определение
        # и молча не открывает диалог
        panel = ui.allToolbarPanels.itemById('SolidCreatePanel')
        if panel:
            old_ctrl = panel.controls.itemById(CMD_ID)
            if old_ctrl:
                old_ctrl.deleteMe()
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            CMD_ID, 'Ящик Ultrabox',
            'Создаёт ящик REJS Ultrabox: металлические боковины, дно, задняя стенка, '
            'фасад со сверловкой и присадка корпуса под направляющие. '
            'Выберите боковины корпуса — ящик встанет в него сам.',
            os.path.join(_DIR, 'resources', 'ultrabox'))
        on_created = _CreatedHandler()
        cmd_def.commandCreated.add(on_created)
        _handlers.append(on_created)

        if panel:
            panel.controls.addCommand(cmd_def)
    except Exception:
        adsk.core.Application.get().userInterface.messageBox(
            'Ultrabox run failed:\n' + traceback.format_exc())


def stop(context):
    try:
        app, ui = _ui()
        panel = ui.allToolbarPanels.itemById('SolidCreatePanel')
        if panel:
            ctrl = panel.controls.itemById(CMD_ID)
            if ctrl:
                ctrl.deleteMe()
        cmd_def = ui.commandDefinitions.itemById(CMD_ID)
        if cmd_def:
            cmd_def.deleteMe()
    except Exception:
        pass

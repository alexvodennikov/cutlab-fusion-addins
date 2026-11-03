# -*- coding: utf-8 -*-
"""REJS Ultrabox — каталог и расчёт деталей ящика.

Все размеры в мм. Данные сняты с:
  Rejs_UltraBox_zew_wew_manual.pdf (раскрой, присадка, установочные размеры)
  UB-ulotka-a5-z-push-open-RUS.pdf (артикулы, характеристики)

Система координат ящика (правая):
  X — по ширине проёма, 0 на внутренней плоскости ЛЕВОЙ стенки корпуса, LW — правой
  Y — по глубине, 0 на переднем торце корпуса, вглубь корпуса положительно
  Z — вверх, 0 = низ направляющей (низ занимаемого ящиком пространства)
"""

# ----- каталог -----
HEIGHTS = (86, 118, 167, 199)          # H, высота боковины = высота задней стенки
LENGTHS = (300, 350, 400, 450, 500, 550)  # NL, номинальная длина направляющей

# формулы раскроя (плита 16 мм по каталогу; толщина — параметр)
BOTTOM_W_OFFSET = 75    # ширина дна = LW - 75
BOTTOM_L_OFFSET = 24    # длина дна  = NL - 24
BACK_W_OFFSET = 87      # ширина задней стенки = LW - 87
INNER_FRONT_W_OFFSET = 98   # подрезка металлического фасада внутр. ящика = LW - 98
INNER_RAIL_W_OFFSET = 85    # подрезка релинга = LW - 85
SYNC_BAR_W_OFFSET = 128     # планка синхронизатора = LW - 128

# требуемое пространство в шкафу, E(min) по высоте
E_MIN = {86: 115, 118: 150, 167: 198, 199: 230}          # soft-close / push-open без синхр.
E_MIN_SYNC = {86: 132, 118: 167, 167: 215, 199: 247}     # push-open с синхронизацией
DEPTH_EXTRA_STD = 3     # мин. внутренняя глубина = NL + 3
DEPTH_EXTRA_INNER = 12  # внутренний ящик: NL + 3 + 9

# присадка боковин корпуса под направляющие (от переднего торца, система 32)
CAB_HOLE_ROWS_Z = (33.0, 49.0)     # высоты рядов от низа направляющей
CAB_HOLE_COLS = {                  # колонки отверстий по Y от переднего торца
    'short': (37.0, 229.0, 261.0),   # NL 300 / 350 / 400  (37, 37+192, 37+224)
    'long':  (37.0, 261.0, 293.0),   # NL 450 / 500 / 550  (37, 37+224, 37+256)
}
CAB_HOLE_D = 5.0       # евровинт: ø5
CAB_HOLE_DEPTH = 13.0

# сверловка фасада (пилотные отверстия ø2 под шурупы 3,8x19)
# вертикальные позиции от низа пространства ящика (z=0): J(min)=47.5, шаг 32 / K / L
FACADE_ROWS_Z = {
    86:  (47.5, 79.5),
    118: (47.5, 79.5, 111.5),
    167: (47.5, 79.5, 143.5, 175.5),   # K=64, L=32
    199: (47.5, 79.5, 143.5, 175.5),
}
FACADE_HOLE_X_INSET = 15.0   # колонка отверстий: 15 мм от внутренней плоскости стенки корпуса
FACADE_HOLE_D = 2.0
FACADE_HOLE_DEPTH = 12.0

# габариты металлических частей для 3D-модели (визуальные, не каталожные)
SIDE_ZONE_W = 15.5        # направляющая + стенка боковины от стенки корпуса
SIDE_WALL_T = 12.5        # видимая толщина боковины
BOTTOM_UNDERSIDE_Z = 10.0 # низ дна над низом направляющей
SLIDE_H = 25.0            # высота корпуса направляющей
SLIDE_W = 15.5

# ----- артикулы (страница 3 листовки) -----
_RUNNER_SC_BASE = {86: 1157, 118: 1163, 167: 1169, 199: 1175}
_RUNNER_PO_BASE = {86: 1208, 118: 1214, 167: 1220, 199: 1226}
_COVER_SET = {86: '1182', 118: '1183', 167: '1184', 199: '1185'}
_RAIL_BY_NL = {300: '1238', 350: '1239', 400: '1240', 450: '1232', 500: '1233', 550: '1241'}


def runner_article(h, nl, push_open=False):
    base = (_RUNNER_PO_BASE if push_open else _RUNNER_SC_BASE)[h]
    return 'TH03.%d.01' % (base + LENGTHS.index(nl))


def compute(cfg):
    """cfg: dict → полный расчёт ящика.

    ключи cfg (все мм):
      h            86|118|167|199
      nl           300..550
      lw           внутренняя ширина корпуса
      push_open    bool
      sync         bool (синхронизатор push-open)
      inner        bool (внутренний ящик)
      bottom_t     толщина дна (16)
      back_t       толщина задней стенки (16)
      facade_t     толщина фасада (18)
      facade_w     ширина фасада (0 = авто: LW + 2*16 - 4)
      facade_h     высота фасада (0 = авто: E_min + 20)
      facade_below вылет фасада ниже z=0 (перекрытие вниз)
      facade_gap   зазор фасад-торец корпуса по Y
      side_t       толщина боковин корпуса (для авто-ширины фасада)
    """
    h = int(cfg['h']); nl = int(cfg['nl']); lw = float(cfg['lw'])
    inner = bool(cfg.get('inner'))
    push_open = bool(cfg.get('push_open'))
    sync = bool(cfg.get('sync'))
    bottom_t = float(cfg.get('bottom_t', 16.0))
    back_t = float(cfg.get('back_t', 16.0))
    side_t = float(cfg.get('side_t', 16.0))

    if h not in HEIGHTS:
        raise ValueError('H must be one of %s' % (HEIGHTS,))
    if nl not in LENGTHS:
        raise ValueError('NL must be one of %s' % (LENGTHS,))

    warnings = []
    e_min = (E_MIN_SYNC if (push_open and sync) else E_MIN)[h]
    depth_min = nl + (DEPTH_EXTRA_INNER if inner else DEPTH_EXTRA_STD)

    bottom_w = lw - BOTTOM_W_OFFSET
    bottom_l = nl - BOTTOM_L_OFFSET
    back_w = lw - BACK_W_OFFSET
    if bottom_w <= 0:
        raise ValueError('LW too small')
    if lw > nl and push_open:
        warnings.append('LW > NL: для push-open нужен синхронизатор (TH03.1235.00.000)')

    # раскрой листовых деталей
    panels = [
        dict(name='Dno', w=round(bottom_w, 1), l=round(bottom_l, 1), t=bottom_t,
             note='дно, ширина LW-75, длина NL-24'),
        dict(name='Zadnyaya_stenka', w=round(back_w, 1), l=float(h), t=back_t,
             note='задняя стенка, ширина LW-87, высота H'),
    ]

    # позиции деталей в системе координат ящика.
    # Дно стоит ВПЛОТНУЮ к фасаду (видео сборки REJS): замки крепления фасада
    # находятся в зоне боковин, шире дна, и места по глубине не занимают.
    # Все 24 мм формулы NL-24 уходят назад -- под крепления задней стенки.
    y_box_front = 0.0 + (9.0 if inner else 0.0)    # передний край дна и боковин
    z_bottom = BOTTOM_UNDERSIDE_Z
    layout = dict(
        bottom=dict(x=(lw - bottom_w) / 2.0, y=y_box_front, z=z_bottom,
                    w=bottom_w, l=bottom_l, t=bottom_t),
        back=dict(x=(lw - back_w) / 2.0,
                  y=y_box_front + bottom_l - back_t, z=z_bottom + bottom_t,
                  w=back_w, hgt=float(h), t=back_t),
        sides=dict(zone_w=SIDE_ZONE_W, wall_t=SIDE_WALL_T,
                   y0=y_box_front, length=nl - 10.0,
                   z0=z_bottom, hgt=float(h) + bottom_t),
        slide=dict(w=SLIDE_W, hgt=SLIDE_H, y0=0.0 + (9.0 if inner else 0.0), length=float(nl)),
    )

    # фасад
    facade = None
    facade_holes = []
    if not inner:
        f_t = float(cfg.get('facade_t', 18.0))
        f_w = float(cfg.get('facade_w') or 0) or (lw + 2 * side_t - 4.0)
        f_h = float(cfg.get('facade_h') or 0) or (e_min + 20.0)
        f_below = float(cfg.get('facade_below', 20.0))
        f_gap = float(cfg.get('facade_gap', 0.0))
        facade = dict(w=f_w, hgt=f_h, t=f_t,
                      x=(lw - f_w) / 2.0, y=-f_gap - f_t, z=-f_below)
        rows = FACADE_ROWS_Z[h]
        lowest_from_edge = rows[0] + f_below
        if lowest_from_edge < 47.5:
            warnings.append('J=%.1f < 47.5 мм: нижний ряд отверстий слишком близко к кромке фасада' % lowest_from_edge)
        for x in (FACADE_HOLE_X_INSET, lw - FACADE_HOLE_X_INSET):
            for z in rows:
                facade_holes.append(dict(x=x, z=z, d=FACADE_HOLE_D, depth=FACADE_HOLE_DEPTH))
        panels.append(dict(name='Fasad', w=round(f_w, 1), l=round(f_h, 1), t=f_t,
                           note='фасад, размер задаётся пользователем'))
    else:
        panels.append(dict(name='Metal_front', w=round(lw - INNER_FRONT_W_OFFSET, 1), l=float(h), t=1.0,
                           note='металлическая передняя панель TH03.1181.01, подрезка LW-98'))

    # присадка корпуса под направляющие
    cols = CAB_HOLE_COLS['short' if nl <= 400 else 'long']
    cabinet_holes = [dict(y=y, z=z, d=CAB_HOLE_D, depth=CAB_HOLE_DEPTH)
                     for y in cols for z in CAB_HOLE_ROWS_Z]

    articles = dict(runner_set=runner_article(h, nl, push_open))
    if inner:
        articles['front_panel'] = 'TH03.1181.01 (подрезка до %.0f мм)' % (lw - INNER_FRONT_W_OFFSET)
        if h in (167, 199):
            articles['front_rail'] = 'TH03.1186.01 (подрезка до %.0f мм)' % (lw - INNER_RAIL_W_OFFSET)
    if push_open and sync:
        articles['synchronizer'] = 'TH03.1235.00.000 (планка L=%.0f)' % (lw - SYNC_BAR_W_OFFSET)

    return dict(h=h, nl=nl, lw=lw, inner=inner, push_open=push_open, sync=sync,
                e_min=e_min, depth_min=depth_min,
                panels=panels, layout=layout, facade=facade,
                facade_holes=facade_holes, cabinet_holes=cabinet_holes,
                articles=articles, warnings=warnings)


def cutlist_text(res):
    lines = ['Ultrabox H%d NL%d LW%.0f%s' % (res['h'], res['nl'], res['lw'],
             ' (внутренний)' if res['inner'] else '')]
    lines.append('Мин. пространство: высота E=%d, глубина %d' % (res['e_min'], res['depth_min']))
    lines.append('Комплект: %s' % res['articles']['runner_set'])
    for k, v in res['articles'].items():
        if k != 'runner_set':
            lines.append('  + %s: %s' % (k, v))
    lines.append('Раскрой:')
    for p in res['panels']:
        lines.append('  %-16s %7.1f x %7.1f x %4.1f  %s' % (p['name'], p['w'], p['l'], p['t'], p['note']))
    for w in res['warnings']:
        lines.append('! ' + w)
    return '\n'.join(lines)

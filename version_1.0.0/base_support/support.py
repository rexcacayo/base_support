"""Base Support: analiza cómo apoya la figura y le hace una base plana o una peana."""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import common, meshio, meshops as mo


# --------------------------------------------------------------------------- geometría 2D
def convex_hull_2d(P, grid=0.05):
    """Casco convexo 2D (cadena monótona). Para nubes grandes se queda primero con los
    extremos de cada columna de una rejilla fina: el casco es el mismo y va mucho más rápido."""
    P = np.asarray(P, float)
    if len(P) < 3:
        return P
    if len(P) > 5000:
        col = np.floor(P[:, 0] / grid).astype(np.int64)
        order = np.lexsort((P[:, 1], col))
        cs = col[order]
        first = np.r_[True, cs[1:] != cs[:-1]]
        last = np.r_[cs[1:] != cs[:-1], True]
        P = np.vstack([P[order[first]], P[order[last]]])
    pts = sorted(set(map(tuple, np.round(P, 6).tolist())))
    if len(pts) < 3:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def poly_area(H):
    if len(H) < 3:
        return 0.0
    x, y = H[:, 0], H[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def inside_margin(H, p):
    """Distancia con signo del punto al borde del polígono convexo (positiva = dentro)."""
    if len(H) < 3:
        return -float('inf') if len(H) == 0 else -float(np.min(np.linalg.norm(H - p, axis=1)))
    best = float('inf')
    for i in range(len(H)):
        a, b = H[i], H[(i + 1) % len(H)]
        e = b - a
        n = np.array([e[1], -e[0]]) / max(np.linalg.norm(e), 1e-12)   # normal hacia fuera (antihorario)
        best = min(best, -float(np.dot(p - a, n)))
    return best


def center_of_mass(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    vol6 = np.einsum('ij,ij->i', a, np.cross(b, c))
    total = vol6.sum()
    if abs(total) < 1e-9:
        _n, ar = mo.face_normals_areas(V, F)
        return ((a + b + c) / 3 * ar[:, None]).sum(0) / max(ar.sum(), 1e-12)
    return ((a + b + c) / 4 * vol6[:, None]).sum(0) / total


def section_area_at(V, F, z):
    """Área aproximada de la sección horizontal a la altura z (casco convexo de los cruces)."""
    za, zb = V[F[:, 0], 2], V[F[:, 1], 2]
    pts = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        p, q = V[F[:, i]], V[F[:, j]]
        m = (p[:, 2] - z) * (q[:, 2] - z) < 0
        if m.any():
            t = (z - p[m, 2]) / (q[m, 2] - p[m, 2])
            pts.append(p[m, :2] + (q[m, :2] - p[m, :2]) * t[:, None])
    if not pts:
        return 0.0, np.zeros((0, 2))
    P = np.vstack(pts)
    return P, None


# --------------------------------------------------------------------------- análisis
def analyze(context, obj, unit='AUTO', tol=0.3):
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, _m = meshio.read_arrays(context, obj, mm)
    z0 = float(V[:, 2].min())
    height = float(V[:, 2].max() - z0)
    contact_v = V[V[:, 2] <= z0 + tol]
    fz = V[F][:, :, 2]
    cf = np.all(fz <= z0 + tol, axis=1)
    nrm, ar = mo.face_normals_areas(V, F)
    down = cf & (nrm[:, 2] < -0.5)
    contact_area = float((ar[down] * -nrm[down, 2]).sum())
    hull = convex_hull_2d(contact_v[:, :2])
    footprint = convex_hull_2d(V[:, :2])
    com = center_of_mass(V, F)
    margin = inside_margin(hull, com[:2])
    # zonas de apoyo separadas (pies)
    zones = 0
    if down.any():
        Fd = F[down]
        lab = mo.vertex_components(len(V), Fd) if len(Fd) else np.zeros(0)
        zones = len(np.unique(lab)) if len(Fd) else 0
    support_area = poly_area(hull)
    foot_area = poly_area(footprint)
    if margin < 0:
        verdict, text = 'bad', 'Se cae: el centro de gravedad queda fuera del apoyo'
    elif contact_area < max(20.0, 0.03 * foot_area):
        verdict, text = 'warn', 'Apoya poco: puede despegarse o volcar al imprimir'
    elif margin < 0.05 * max(1.0, math.sqrt(foot_area)):
        verdict, text = 'warn', 'Estable, pero muy al límite'
    else:
        verdict, text = 'ok', 'Apoya bien y es estable'
    return {'unit': code, 'mm': mm, 'z0': z0, 'height': height, 'contact_area': contact_area,
            'zones': zones, 'support_area': support_area, 'foot_area': foot_area,
            'com': com, 'margin': margin, 'verdict': verdict, 'text': text,
            'suggest_cut': suggest_cut(V, F, z0, foot_area)}


def suggest_cut(V, F, z0, foot_area, max_cut=3.0):
    """Altura de corte para tener un apoyo decente: la menor que da ≥ 8 % de la huella
    (o 40 mm²), sin pasar de `max_cut` mm."""
    target = max(40.0, 0.08 * foot_area)
    # solo hacen falta los triángulos de la parte baja
    low = (V[F][:, :, 2].min(1) <= z0 + max_cut + 1e-6)
    F = F[low]
    for h in np.arange(0.2, max_cut + 1e-9, 0.2):
        P, _ = section_area_at(V, F, z0 + h)
        if len(P) >= 3 and _sum_islands_area(P) >= target:
            return float(round(h, 2))
    return float(max_cut)


def _sum_islands_area(P, cell=2.0):
    """Área aproximada de varias islas (pies separados): se agrupan los puntos por celdas
    vecinas de `cell` mm y se suma el casco convexo de cada grupo."""
    if len(P) < 3:
        return 0.0
    keys = np.floor(P / cell).astype(np.int64)
    uk, lab = np.unique(keys, axis=0, return_inverse=True)
    lab = lab.reshape(-1)
    n = len(uk)
    # celdas vecinas (8-conexas) por búsqueda en un diccionario de celdas
    index = {tuple(k): i for i, k in enumerate(uk.tolist())}
    a, b = [], []
    for i, (kx, ky) in enumerate(uk.tolist()):
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            j = index.get((kx + dx, ky + dy))
            if j is not None:
                a.append(i); b.append(j)
    comp = mo.components(n, np.array(a, np.int64), np.array(b, np.int64)) if a else np.arange(n)
    plab = comp[lab]
    order = np.argsort(plab, kind='stable')
    splits = np.nonzero(np.diff(plab[order]))[0] + 1
    total = 0.0
    for grp in np.split(order, splits):
        if len(grp) >= 3:
            total += poly_area(convex_hull_2d(P[grp]))
    return total


# --------------------------------------------------------------------------- acciones
def flat_base(context, obj, cut_mm, unit='AUTO', drop_to_floor=True):
    """Corta a ras `cut_mm` por encima del punto más bajo y tapa el corte."""
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, _m = meshio.read_arrays(context, obj, 1.0)
    z0 = float(V[:, 2].min())
    zc = z0 + cut_mm / mm
    common.require_solid(context, obj)
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    out = common._half(context, obj, Vector((0, 0, zc)), Vector((0, 0, 1)), True, f'{obj.name}_base_plana', col)
    if drop_to_floor:
        out.location.z -= zc
    out[common.UNIT_PROP] = code
    out['taller_origen'] = obj.name
    obj.hide_set(True); obj.hide_render = True
    meshio.select_only(context, out)
    return out


def _outline(shape, center, radius, rx, ry, segments=96):
    cx, cy = center
    if shape == 'CIRCLE':
        a = np.linspace(0, 2 * math.pi, segments, endpoint=False)
        return np.stack([cx + radius * np.cos(a), cy + radius * np.sin(a)], 1)
    if shape == 'HEX':
        a = np.linspace(0, 2 * math.pi, 6, endpoint=False) + math.pi / 6
        return np.stack([cx + radius * np.cos(a), cy + radius * np.sin(a)], 1)
    if shape == 'OVAL':
        a = np.linspace(0, 2 * math.pi, segments, endpoint=False)
        return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], 1)
    # cuadrada con esquinas redondeadas
    r = min(rx, ry) * 0.18
    pts = []
    for (sx, sy), start in (((1, 1), 0), ((-1, 1), 90), ((-1, -1), 180), ((1, -1), 270)):
        ccx, ccy = cx + sx * (rx - r), cy + sy * (ry - r)
        for k in range(9):
            ang = math.radians(start + k * 90 / 8)
            pts.append((ccx + r * math.cos(ang), ccy + r * math.sin(ang)))
    return np.array(pts)


def _prism(outline, z_bottom, z_top, chamfer):
    """Sólido cerrado: contorno extruido, con chaflán arriba."""
    n = len(outline)
    c = outline.mean(0)
    inner = c + (outline - c) * (1 - chamfer / max(np.linalg.norm(outline - c, axis=1).max(), 1e-9))
    rings = [np.column_stack([outline, np.full(n, z_bottom)]),
             np.column_stack([outline, np.full(n, z_top - chamfer)]),
             np.column_stack([inner, np.full(n, z_top)])]
    V = np.vstack(rings + [[c[0], c[1], z_bottom], [c[0], c[1], z_top]])
    cb, ct = 3 * n, 3 * n + 1
    F = []
    for r in range(2):
        for i in range(n):
            j = (i + 1) % n
            a, b, cc, d = r * n + i, r * n + j, (r + 1) * n + j, (r + 1) * n + i
            F += [(a, b, cc), (a, cc, d)]
    for i in range(n):
        j = (i + 1) % n
        F.append((cb, j, i))
        F.append((ct, 2 * n + i, 2 * n + j))
    return V, np.array(F)


def plinth(context, obj, shape='CIRCLE', height_mm=3.0, margin_mm=4.0, chamfer_mm=0.8, embed_mm=None,
           join=True, unit='AUTO'):
    """Peana debajo de la figura. Con `join`, figura y peana quedan en un solo sólido (la
    figura se hunde un poco en la peana para apoyar de lleno)."""
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, _m = meshio.read_arrays(context, obj, mm)
    z0 = float(V[:, 2].min())
    if embed_mm is None:
        embed_mm = suggest_cut(V, F, z0, poly_area(convex_hull_2d(V[:, :2])), max_cut=2.0)
    low = V[V[:, 2] <= z0 + max(embed_mm, 0.5) + 3.0]
    hull = convex_hull_2d(low[:, :2])
    center = hull.mean(0) if len(hull) else V[:, :2].mean(0)
    radius = float(np.linalg.norm(hull - center, axis=1).max()) + margin_mm
    lo, hi = low[:, :2].min(0), low[:, :2].max(0)
    rx, ry = (hi - lo) / 2 + margin_mm
    if shape in ('SQUARE', 'OVAL'):
        center = (lo + hi) / 2
    outline = _outline(shape, center, radius, rx, ry)
    top = z0 + embed_mm
    Vp, Fp = _prism(outline, top - height_mm, top, min(chamfer_mm, height_mm * 0.45))
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    base = meshio.new_object_like(context, obj, f'{obj.name}_peana', Vp / mm, Fp, np.zeros(len(Fp), np.int64))
    base[common.UNIT_PROP] = code
    if join:
        fig = meshio.new_object_like(context, obj, f'{obj.name}_con_peana', *_arrays_bu(context, obj))
        try:
            common.boolean(context, fig, base, 'UNION')
        except common.AddonError:
            common.remove_objects([fig, base])
            raise
        common.remove_objects([base])
        fig[common.UNIT_PROP] = code
        fig['taller_origen'] = obj.name
        obj.hide_set(True); obj.hide_render = True
        meshio.select_only(context, fig)
        return fig
    meshio.select_only(context, base)
    return base


def _arrays_bu(context, obj):
    V, F, m = meshio.read_arrays(context, obj, 1.0)
    return V, F, m


def best_orientation(context, obj, unit='AUTO', max_points=20000):
    """Gira la figura para que apoye sobre su cara plana más grande en la que no vuelca."""
    code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, mat = meshio.read_arrays(context, obj, 1.0)
    com = center_of_mass(V, F)
    P = V
    if len(P) > max_points:
        P = P[np.random.default_rng(0).choice(len(P), max_points, replace=False)]
    bm = bmesh.new()
    for p in P:
        bm.verts.new(p)
    res = bmesh.ops.convex_hull(bm, input=bm.verts[:])
    faces = [g for g in res['geom'] if isinstance(g, bmesh.types.BMFace)]
    groups = {}
    for f in faces:
        n = f.normal.normalized()
        key = (round(n.x, 2), round(n.y, 2), round(n.z, 2))
        g = groups.setdefault(key, {'n': Vector((0, 0, 0)), 'area': 0.0, 'pts': []})
        g['n'] += n * f.calc_area(); g['area'] += f.calc_area()
        g['pts'] += [v.co.copy() for v in f.verts]
    bm.free()
    best, best_score = None, -1.0
    for g in groups.values():
        n = g['n'].normalized()
        q = n.rotation_difference(Vector((0, 0, -1)))
        R = q.to_matrix()
        pts2 = np.array([(R @ p)[:2] for p in g['pts']])
        c2 = np.array((R @ Vector(com))[:2])
        H = convex_hull_2d(pts2)
        m = inside_margin(H, c2)
        if m <= 0:
            continue
        score = g['area'] * (1 + 0.2 * min(m, 10))
        if score > best_score:
            best, best_score = q, score
    if best is None:
        raise common.AddonError('No encuentro ninguna postura estable para esta figura.')
    R = np.array(best.to_matrix())
    V2 = (V - com) @ R.T + com
    V2[:, 2] -= V2[:, 2].min() - V[:, 2].min()
    out = meshio.new_object_like(context, obj, f'{obj.name}_apoyo', V2, F, mat)
    out[common.UNIT_PROP] = code
    out['taller_origen'] = obj.name
    obj.hide_set(True); obj.hide_render = True
    meshio.select_only(context, out)
    angle = math.degrees(best.angle)
    return out, angle

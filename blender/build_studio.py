"""实时看板 · 6 工位机器人工作室舞台（Blender 无界面脚本，可重跑）
用法（在仓库根目录下；BLENDER 指向你的 Blender 4.2+ 可执行文件）：
  "$BLENDER" -b -P blender/build_studio.py -- --export /tmp/studio6-raw.glb      # 网页用模型（再由 export_web.sh 压缩）
  "$BLENDER" -b -P blender/build_studio.py -- --render /tmp/stage.png            # 预览图（Cycles 卡通着色 + Freestyle 粗墨线，透明底）
风格：红黑白高对比、硬阴影、粗黑描边、拼贴纸片和星形。全部几何体由本脚本生成，不用任何外部素材。
配色：红 #E5121D、深红 #8E0B12、黑 #0E0E10、白 #F3F1EC、纯白 #FFFFFF。
场景：厚黑底座 + 白地面的横向长条舞台；后排工位放在高 0.45 的台阶上，并与前排错开半个工位；
红色厚后墙 + 黑色左墙，墙上贴黑白红拼贴纸片、星形和爆炸形；红色虚线 + 箭头绕一圈。
导出物体：
  env（底座、墙、工位、桌上道具、流程线，合成一块，顶点色）
  body_XX（身体，原点在脚底）→ head_XX → eye_XX、lamp_XX；arml_XX / armr_XX（原点在肩膀）
  pen_01..（三角旗）、hand_m / hand_h（钟针）。会动的部件都包在以转轴为原点的同名空物体里。
  XX = 工位序号 01–06。所有颜色写在顶点色里，只用一个材质。
工位是通用的：谁坐哪个工位由看板网页决定（可随时替换），模型里不含任何成员名字。
"""
import bpy, math, sys, argparse, json, os
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--render", default="")
ap.add_argument("--robots", default="")
ap.add_argument("--export", default="")
ap.add_argument("--samples", type=int, default=48)
ap.add_argument("--res", default="2100x900")
ap.add_argument("--slots", type=int, default=6)   # 6 = 看板用的 6 工位舞台（studio6.glb）；0 = 14 工位的大舞台（实验用，看板不用）
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene

# ---------- 配色（红黑白） ----------
RED = "#E5121D"; DRED = "#8E0B12"; BLACK = "#0E0E10"; WHITE = "#F3F1EC"; PURE = "#FFFFFF"
# 沿用旧变量名，免得改动道具代码：纸色→白，朱红→红，群青→黑，明黄→纯白，墨→黑
PAPER = WHITE; PAPER2 = WHITE; PAPERD = "#D9D6D0"; SHADOW = BLACK
ZHU = RED; QING = BLACK; HUANG = PURE; MO = BLACK
def lin(h):
    h = h.lstrip("#"); c = [int(h[i:i+2], 16) / 255 for i in (0, 2, 4)]
    return tuple((v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in c) + (1.0,)

VC = bpy.data.materials.new("VC"); VC.use_nodes = True
nt = VC.node_tree; bsdf = nt.nodes["Principled BSDF"]
ca = nt.nodes.new("ShaderNodeVertexColor"); ca.layer_name = "Col"
nt.links.new(ca.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.85

def act(o):
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o

def paint(o, col):
    me = o.data
    at = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
    c = lin(col)
    for d in at.data: d.color = c
    me.materials.append(VC)

def mk(kind, loc, dims, col, rot=(0, 0, 0), bev=0.0, seg=2, verts=16, smooth=True):
    if kind == "box":
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot); o = bpy.context.object; o.scale = dims
    elif kind == "cyl":
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=dims[0], depth=dims[1], location=loc, rotation=rot); o = bpy.context.object
    elif kind == "sph":
        bpy.ops.mesh.primitive_uv_sphere_add(segments=verts, ring_count=max(6, verts // 2), radius=dims[0], location=loc, rotation=rot); o = bpy.context.object
        if len(dims) == 3: o.scale = (1, dims[1], dims[2])
    elif kind == "cone":
        bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=dims[0], radius2=dims[1], depth=dims[2], location=loc, rotation=rot); o = bpy.context.object
    elif kind == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=dims[0], minor_radius=dims[1], major_segments=verts, minor_segments=8, location=loc, rotation=rot); o = bpy.context.object
    act(o); bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bev > 0:
        m = o.modifiers.new("bev", "BEVEL"); m.width = bev; m.segments = seg; m.limit_method = "ANGLE"
        bpy.ops.object.modifier_apply(modifier=m.name)
    if smooth: bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
    paint(o, col)
    return o

def join(objs, name):
    objs = [o for o in objs if o]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1: bpy.ops.object.join()
    o = bpy.context.object; o.name = name; o.data.name = name
    return o

def set_origin(o, p):
    act(o); sc.cursor.location = p; bpy.ops.object.origin_set(type="ORIGIN_CURSOR"); sc.cursor.location = (0, 0, 0)

def parent(child, par):
    bpy.ops.object.select_all(action="DESELECT"); child.select_set(True); par.select_set(True)
    bpy.context.view_layer.objects.active = par; bpy.ops.object.parent_set(type="OBJECT", keep_transform=True)

def pivotize(o):
    """把会动的物体包进一个同名空物体（原点＝转轴）。网页压缩（量化）会改网格节点的变换，空物体的变换不受影响。"""
    par = o.parent; name = o.name
    o.name = name + "_m"
    e = bpy.data.objects.new(name, None); sc.collection.objects.link(e)
    e.matrix_world = o.matrix_world.copy()
    if par: e.parent = par; e.matrix_parent_inverse = par.matrix_world.inverted()
    mw = o.matrix_world.copy(); o.parent = e; o.matrix_parent_inverse.identity(); o.matrix_world = mw
    return e

# ---------- 成员与布局 ----------
SLOTS = a.slots
# 工位只用占位名（位1、位2…），不读任何名单
ROSTER = [{"short": f"位{i + 1}"} for i in range(14)]
COLORS = [RED, BLACK, RED, PURE, RED, BLACK, RED, PURE, RED, BLACK, RED, PURE, BLACK, RED]
PROPS = ["flag", "books", "pen", "brush", "headset", "keys", "reel", "magnifier", "phone", "chart", "case", "laptop", "scope", "broom"]
if SLOTS:   # 6 工位：通用工位，谁坐都行（网页里可替换），道具不绑定具体角色
    ROSTER = [{"short": f"位{i + 1}"} for i in range(SLOTS)]
    COLORS = [RED, BLACK, PURE, BLACK, RED, PURE]
    PROPS = ["laptop", "pen", "headset", "magnifier", "keys", "phone"]
SP = 2.8; R = 1.6; D = 1.3                                  # SP 工位间距，R 机器人放大倍数（v6 放大），D 工位放大倍数
RISE = 0.45                                                 # 后排台阶高度
POS = {0: (-9.0, 0.3)}                                      # 1 号位：最左端，流程起点和终点（14 工位大舞台）
for i in range(5): POS[1 + i] = (-4.2 + i * SP, 2.55)       # 2–6 后排 左→右（台阶上，和前排错开半个工位）
for i in range(5): POS[6 + i] = (5.6 - i * SP, -1.4)        # 7–11 前排 右→左
RUG_X = 10.9
for i in range(3): POS[11 + i] = (RUG_X + (0.75 if i == 1 else -0.75), 2.6 - i * 2.25)    # 12–14 号位：右侧地毯（错开站，不互相挡）
if SLOTS:   # 后排 3 个在台阶上，前排 3 个错开半个工位
    POS = {0: (-4.2, 2.55), 1: (0.0, 2.55), 2: (4.2, 2.55), 3: (-2.1, -1.4), 4: (2.1, -1.4), 5: (6.3, -1.4)}
def is_back(i): return (i < 3) if SLOTS else (1 <= i <= 5)

def grow(objs, cx, cy, k):
    for o in objs:
        o.location = (cx + (o.location.x - cx) * k, cy + (o.location.y - cy) * k, o.location.z * k)
        o.scale = (o.scale.x * k, o.scale.y * k, o.scale.z * k)
    return objs

FLOOR_Z = 0.0

def desk(x, y, col, big=False):
    w = 1.25 if big else 1.0
    parts = [
        mk("box", (x, y, 0.235), (w * 0.92, 0.46, 0.47), WHITE, bev=0.03),
        mk("box", (x, y, 0.505), (w + 0.08, 0.62, 0.07), BLACK, bev=0.025),
        mk("box", (x - w * 0.1, y - 0.232, 0.25), (w * 0.5, 0.01, 0.16), RED if col != RED else PURE, rot=(0, 0.12, 0), bev=0.0),   # 桌前斜贴的纸签
    ]
    return parts

def desk_prop(kind, x, y, col):
    z = 0.54; P = []
    if kind == "books":
        P += [mk("box", (x - 0.28, y - 0.05, z + 0.04), (0.3, 0.22, 0.08), QING, bev=0.01),
              mk("box", (x - 0.27, y - 0.05, z + 0.12), (0.28, 0.2, 0.07), HUANG, bev=0.01, rot=(0, 0, 0.15)),
              mk("box", (x - 0.28, y - 0.05, z + 0.19), (0.26, 0.19, 0.06), ZHU, bev=0.01, rot=(0, 0, -0.1))]
    elif kind == "keys":
        P += [mk("box", (x, y - 0.1, z + 0.03), (0.78, 0.26, 0.06), MO, bev=0.015)]
        for k in range(7): P.append(mk("box", (x - 0.3 + k * 0.1, y - 0.16, z + 0.065), (0.075, 0.12, 0.02), PAPER2, smooth=False))
    elif kind == "reel":
        P += [mk("cyl", (x - 0.3, y - 0.02, z + 0.2), (0.19, 0.05), MO, rot=(math.pi / 2, 0, 0.3), verts=20),
              mk("cyl", (x - 0.3, y - 0.05, z + 0.2), (0.05, 0.02), PAPER2, rot=(math.pi / 2, 0, 0.3), verts=12),
              mk("box", (x + 0.12, y - 0.1, z + 0.012), (0.5, 0.11, 0.02), MO, rot=(0, 0, -0.25), smooth=False)]
    elif kind == "chart":
        P += [mk("box", (x - 0.15, y - 0.02, z + 0.24), (0.56, 0.06, 0.4), MO, bev=0.03),
              mk("box", (x - 0.15, y - 0.055, z + 0.24), (0.48, 0.01, 0.32), PAPER2),
              mk("box", (x - 0.3, y - 0.065, z + 0.15), (0.08, 0.01, 0.12), QING, smooth=False),
              mk("box", (x - 0.15, y - 0.065, z + 0.18), (0.08, 0.01, 0.18), HUANG, smooth=False),
              mk("box", (x - 0.0, y - 0.065, z + 0.21), (0.08, 0.01, 0.24), ZHU, smooth=False)]
    elif kind == "case":
        P += [mk("box", (x - 0.25, y - 0.08, z + 0.13), (0.4, 0.14, 0.26), MO, bev=0.03),
              mk("torus", (x - 0.25, y - 0.08, z + 0.27), (0.07, 0.018), MO, rot=(math.pi / 2, 0, 0), verts=12),
              mk("box", (x - 0.25, y - 0.152, z + 0.17), (0.06, 0.01, 0.04), HUANG, smooth=False)]
    elif kind == "laptop":
        P += [mk("box", (x, y - 0.1, z + 0.015), (0.56, 0.36, 0.03), MO, bev=0.01),
              mk("box", (x, y + 0.08, z + 0.19), (0.56, 0.03, 0.36), MO, rot=(-0.25, 0, 0), bev=0.01),
              mk("box", (x, y + 0.06, z + 0.19), (0.48, 0.01, 0.28), QING, rot=(-0.25, 0, 0))]
    elif kind == "scope":
        P += [mk("cyl", (x - 0.25, y - 0.05, z + 0.25), (0.012, 0.45), MO, rot=(0.2, 0.2, 0), verts=6),
              mk("cyl", (x - 0.2, y - 0.1, z + 0.5), (0.09, 0.62), HUANG, rot=(0.9, 0, -0.6), verts=14),
              mk("cyl", (x + 0.02, y - 0.38, z + 0.72), (0.11, 0.08), MO, rot=(0.9, 0, -0.6), verts=14)]
    elif kind == "headset":
        P += [mk("cyl", (x - 0.3, y - 0.05, z + 0.1), (0.015, 0.2), MO, verts=6),
              mk("sph", (x - 0.3, y - 0.05, z + 0.25), (0.06, 1, 1.3), MO, verts=12),
              mk("cyl", (x - 0.3, y - 0.05, z + 0.008), (0.08, 0.016), MO, verts=12)]
    elif kind == "flag":
        P += [mk("box", (x - 0.35, y - 0.1, z + 0.02), (0.36, 0.26, 0.03), PAPER, rot=(0, 0, 0.12)),
              mk("box", (x - 0.33, y - 0.1, z + 0.05), (0.3, 0.2, 0.02), PAPER2, rot=(0, 0, -0.08))]
    return P

def robot(n, x, y, col, prop):
    S = 1.0
    def L(px, py, pz): return (x + px * S, y + py * S, pz * S)
    bod = [
        mk("cyl", L(-0.13, 0, 0.16), (0.07 * S, 0.32 * S), MO, verts=10),
        mk("cyl", L(0.13, 0, 0.16), (0.07 * S, 0.32 * S), MO, verts=10),
        mk("box", L(0, 0, 0.56), (0.56 * S, 0.42 * S, 0.5 * S), col, bev=0.09 * S, seg=3),
        mk("box", L(0, -0.212, 0.6), (0.26 * S, 0.02 * S, 0.15 * S), PAPER2, bev=0.02 * S),
        mk("cyl", L(0, 0, 0.84), (0.07 * S, 0.1 * S), MO, verts=10),
    ]
    arml = [mk("cyl", L(-0.36, -0.02, 0.6), (0.055 * S, 0.3 * S), MO, rot=(0.3, 0.25, 0), verts=8),
            mk("sph", L(-0.4, -0.1, 0.46), (0.075 * S,), PAPER2, verts=10)]
    armr = [mk("cyl", L(0.36, -0.02, 0.6), (0.055 * S, 0.3 * S), MO, rot=(0.3, -0.25, 0), verts=8),
            mk("sph", L(0.4, -0.1, 0.46), (0.075 * S,), PAPER2, verts=10)]
    # 手持道具（右手 = +x 侧）
    hx, hy, hz = 0.42, -0.14, 0.5
    if prop == "pen":
        armr += [mk("cyl", L(hx + 0.03, hy - 0.04, hz + 0.2), (0.05 * S, 0.6 * S), HUANG, rot=(0.3, 0.25, 0), verts=8),
                mk("cone", L(hx - 0.04, hy - 0.13, hz - 0.15), (0.05 * S, 0.0, 0.14 * S), MO, rot=(0.3 + math.pi, -0.25, 0), verts=8),
                mk("cyl", L(hx + 0.1, hy + 0.04, hz + 0.5), (0.052 * S, 0.06 * S), ZHU, rot=(0.3, 0.25, 0), verts=8)]
    elif prop == "brush":
        armr += [mk("cyl", L(hx, hy, hz + 0.16), (0.032 * S, 0.5 * S), MO, rot=(0.25, 0, 0), verts=8),
                mk("cyl", L(hx, hy - 0.08, hz + 0.43), (0.06 * S, 0.08 * S), PAPER2, rot=(0.25, 0, 0), verts=10),
                mk("cone", L(hx, hy - 0.11, hz + 0.56), (0.07 * S, 0.0, 0.2 * S), ZHU if col != ZHU else QING, rot=(0.25, 0, 0), verts=10)]
    elif prop == "magnifier":
        armr += [mk("cyl", L(hx, hy, hz + 0.1), (0.025 * S, 0.24 * S), MO, rot=(0.2, 0, 0), verts=8),
                mk("torus", L(hx, hy - 0.03, hz + 0.3), (0.11 * S, 0.025 * S), MO, rot=(math.pi / 2, 0, 0), verts=18),
                mk("cyl", L(hx, hy - 0.03, hz + 0.3), (0.1 * S, 0.01 * S), PAPER2, rot=(math.pi / 2, 0, 0), verts=18)]
    elif prop == "phone":
        armr += [mk("box", L(hx, hy - 0.03, hz + 0.12), (0.13 * S, 0.03 * S, 0.24 * S), MO, rot=(0.25, 0, 0), bev=0.02),
                mk("box", L(hx, hy - 0.05, hz + 0.12), (0.1 * S, 0.01 * S, 0.19 * S), HUANG, rot=(0.25, 0, 0))]
    elif prop == "broom":
        armr += [mk("cyl", L(hx + 0.05, hy, hz + 0.05), (0.022 * S, 0.95 * S), HUANG, rot=(0, -0.12, 0), verts=8),
                mk("box", L(hx + 0.1, hy, hz - 0.4), (0.24 * S, 0.1 * S, 0.16 * S), MO, rot=(0, -0.12, 0), bev=0.03)]
    K = R * (1.22 if (n == 1 and not SLOTS) else 1.0)
    body = join(grow(bod, x, y, K), f"body_{n:02d}")
    al = join(grow(arml, x, y, K), f"arml_{n:02d}"); ar = join(grow(armr, x, y, K), f"armr_{n:02d}")
    # 头
    hz0 = 0.84 * S
    hed = [
        mk("box", L(0, 0, 1.12), (0.76 * S, 0.56 * S, 0.52 * S), PAPER2, bev=0.14 * S, seg=3),
        mk("box", L(0, -0.275, 1.1), (0.6 * S, 0.04 * S, 0.32 * S), MO, bev=0.08 * S, seg=2),
        mk("cyl", L(-0.395, 0, 1.1), (0.09 * S, 0.07 * S), col, rot=(0, math.pi / 2, 0), verts=12),
        mk("cyl", L(0.395, 0, 1.1), (0.09 * S, 0.07 * S), col, rot=(0, math.pi / 2, 0), verts=12),
        mk("cyl", L(0, 0, 1.45), (0.018 * S, 0.16 * S), MO, verts=6),
    ]
    if prop == "headset":
        hed += [mk("torus", L(0, 0, 1.16), (0.42 * S, 0.04 * S), MO, rot=(math.pi / 2, 0, 0), verts=24),
                mk("cyl", L(-0.44, 0, 1.1), (0.14 * S, 0.09 * S), MO, rot=(0, math.pi / 2, 0), verts=14),
                mk("cyl", L(0.44, 0, 1.1), (0.14 * S, 0.09 * S), MO, rot=(0, math.pi / 2, 0), verts=14),
                mk("cyl", L(0.34, -0.25, 0.96), (0.018 * S, 0.32 * S), MO, rot=(0, 1.1, 0.6), verts=6),
                mk("sph", L(0.17, -0.37, 0.92), (0.06 * S,), HUANG, verts=10)]
    if prop == "flag":
        hed += [mk("cyl", L(0.22, 0.05, 1.62), (0.014 * S, 0.5 * S), MO, verts=6),
                mk("box", L(0.42, 0.05, 1.75), (0.38 * S, 0.012 * S, 0.22 * S), ZHU, smooth=False),
                mk("cyl", L(-0.08, 0.02, 1.46), (0.17 * S, 0.16 * S), MO, verts=18),
                mk("cyl", L(-0.08, 0.02, 1.4), (0.26 * S, 0.025 * S), MO, verts=20),
                mk("cyl", L(-0.08, 0.02, 1.43), (0.175 * S, 0.035 * S), ZHU, verts=18)]   # 小礼帽（朱红帽带）
    head = join(grow(hed, x, y, K), f"head_{n:02d}")
    eyes = join(grow([mk("cyl", L(-0.13, -0.31, 1.1), (0.085, 0.05), PURE, rot=(math.pi / 2, 0, 0), verts=14),
                      mk("cyl", L(0.13, -0.31, 1.1), (0.085, 0.05), PURE, rot=(math.pi / 2, 0, 0), verts=14)], x, y, K), f"eye_{n:02d}")
    lamp = grow([mk("sph", L(0, 0, 1.56), (0.075,), col, verts=12)], x, y, K)[0]; lamp.name = f"lamp_{n:02d}"; lamp.data.name = lamp.name
    set_origin(body, (x, y, 0)); set_origin(head, (x, y, hz0 * K)); set_origin(eyes, (x, y - 0.3 * K, 1.1 * K)); set_origin(lamp, (x, y, 1.56 * K))
    set_origin(al, (x - 0.33 * K, y, 0.74 * K)); set_origin(ar, (x + 0.33 * K, y, 0.74 * K))
    parent(eyes, head); parent(lamp, head); parent(head, body); parent(al, body); parent(ar, body)
    for o in (eyes, lamp, al, ar): pivotize(o)
    return body

# ---------- 场景 ----------
env = []
X0, X1, Y0, Y1 = (-7.4, 8.8, -3.5, 4.3) if SLOTS else (-10.8, 13.0, -3.5, 4.3)
# 厚底座：黑色体块 + 白色地面（四边露黑边），正面一条红色斜纹饰带
env.append(mk("box", ((X0 + X1) / 2, (Y0 + Y1) / 2, -0.45), (X1 - X0 + 0.3, Y1 - Y0 + 0.3, 0.9), BLACK, bev=0.05))
env.append(mk("box", ((X0 + X1) / 2, (Y0 + Y1) / 2, -0.005), (X1 - X0, Y1 - Y0, 0.04), WHITE, bev=0.01))
for k in range(int((X1 - X0 - 1.0) / 1.5) + 1):
    env.append(mk("box", (X0 + 0.9 + k * 1.5, Y0 - 0.152, -0.45), (0.22, 0.01, 0.95), RED, rot=(0, 0.6, 0), smooth=False))
# 后排台阶（只到地毯前）：黑侧面 + 白顶
RX1 = X1 if SLOTS else 8.75
env.append(mk("box", ((X0 + RX1) / 2, (1.85 + Y1) / 2, RISE / 2 - 0.02), (RX1 - X0, Y1 - 1.85, RISE + 0.04), BLACK, bev=0.03))
env.append(mk("box", ((X0 + RX1) / 2, (1.85 + Y1) / 2 + 0.03, RISE + 0.005), (RX1 - X0 - 0.12, Y1 - 1.85 - 0.06, 0.03), WHITE))
env.append(mk("box", ((X0 + RX1) / 2, 1.85 - 0.012, RISE * 0.55), (RX1 - X0, 0.01, 0.07), RED, smooth=False))
# 厚墙：后墙红、左墙黑，墙顶压一条黑边
env.append(mk("box", ((X0 + X1) / 2, Y1 + 0.2, 1.3), (X1 - X0 + 0.3, 0.4, 2.9), RED, bev=0.03))
env.append(mk("box", ((X0 + X1) / 2, Y1 - 0.005, 0.12), (X1 - X0, 0.02, 0.24), BLACK, smooth=False))
env.append(mk("box", ((X0 + X1) / 2, Y1 + 0.2, 2.78), (X1 - X0 + 0.34, 0.44, 0.08), BLACK, smooth=False))
env.append(mk("box", (X0 - 0.2, (Y0 + Y1) / 2 + 0.2, 1.3), (0.4, Y1 - Y0 + 0.4, 2.9), BLACK, bev=0.03))
# 墙上拼贴：黑底衬 + 白 / 黑 / 红纸片，歪着贴
COLL = [(-7.6, 1.6, 1.0, 1.55, PURE, 0.08), (-2.4, 1.1, 0.8, 1.75, BLACK, -0.1), (1.2, 2.1, 0.9, 1.5, PURE, 0.05),
        (5.2, 1.2, 1.1, 1.6, BLACK, -0.07), (9.2, 1.4, 0.75, 1.75, PURE, 0.09), (12.1, 0.9, 1.0, 1.5, BLACK, -0.06)]
if SLOTS: COLL = [(-4.4, 1.3, 0.9, 1.6, PURE, 0.08), (-1.0, 1.0, 0.8, 1.75, BLACK, -0.1), (2.2, 1.8, 0.9, 1.5, PURE, 0.05), (6.6, 1.3, 1.0, 1.6, BLACK, -0.07)]
for (cx, w, h, z, col, r) in COLL:
    env.append(mk("box", (cx + 0.08, Y1 - 0.004, z - 0.08), (w, 0.01, h), BLACK if col != BLACK else PURE, rot=(0, r, 0), smooth=False))
    env.append(mk("box", (cx, Y1 - 0.012, z), (w, 0.012, h), col, rot=(0, r, 0), smooth=False))
    env.append(mk("box", (cx - w * 0.12, Y1 - 0.02, z + h * 0.1), (w * 0.5, 0.008, h * 0.18), RED, rot=(0, r - 0.05, 0), smooth=False))
for (cy, w, h, z, col, r) in [(1.9, 1.3, 0.9, 1.5, RED, 0.06), (-1.6, 1.0, 1.15, 1.4, PURE, -0.05)]:
    env.append(mk("box", (X0 + 0.004, cy - 0.08, z - 0.08), (0.01, w, h), PURE if col == RED else RED, rot=(r, 0, 0), smooth=False))
    env.append(mk("box", (X0 + 0.012, cy, z), (0.012, w, h), col, rot=(r, 0, 0), smooth=False))
# 星形 / 爆炸形（自己画的多角星，薄片贴墙）
def star(cx, cz, ro, ri, n, col, y=None, x=None, rot=0.0, th=0.012):
    vs = []
    for k in range(2 * n):
        rr = ro if k % 2 == 0 else ri; an = rot + k * math.pi / n
        vs.append((math.cos(an) * rr, math.sin(an) * rr))
    me = bpy.data.meshes.new("star"); N = len(vs)
    if x is None: V = [(cx + u, y - 0.0, cz + v) for u, v in vs] + [(cx + u, y - th, cz + v) for u, v in vs] + [(cx, y - th, cz), (cx, y, cz)]
    else: V = [(x, cx + u, cz + v) for u, v in vs] + [(x + th, cx + u, cz + v) for u, v in vs] + [(x + th, cx, cz), (x, cx, cz)]
    F = [(N + k, N + (k + 1) % N, 2 * N) for k in range(N)] + [((k + 1) % N, k, 2 * N + 1) for k in range(N)] + [(k, (k + 1) % N, N + (k + 1) % N, N + k) for k in range(N)]
    me.from_pydata(V, [], F); me.update()
    o = bpy.data.objects.new("star", me); sc.collection.objects.link(o); paint(o, col); return o
env += [star(-4.6, 2.1, 0.55, 0.25, 5, BLACK, y=Y1 - 0.004, rot=0.3), star(-4.6, 2.1, 0.42, 0.19, 5, PURE, y=Y1 - 0.02, rot=0.3),
        star(3.3, 2.2, 0.45, 0.2, 5, PURE, y=Y1 - 0.004, rot=-0.2), star(7.3, 1.25, 0.75, 0.48, 12, BLACK, y=Y1 - 0.004, rot=0.1),
        star(7.3, 1.25, 0.6, 0.38, 12, PURE, y=Y1 - 0.016, rot=0.1), star(10.6, 2.25, 0.35, 0.16, 5, BLACK, y=Y1 - 0.004),
        star(0.2, 1.6, 0.9, 0.55, 14, RED, x=X0 + 0.004, rot=0.2), star(0.2, 1.6, 0.7, 0.42, 14, PURE, x=X0 + 0.016, rot=0.2)] if not SLOTS else \
       [star(-2.6, 2.15, 0.5, 0.23, 5, BLACK, y=Y1 - 0.004, rot=0.3), star(-2.6, 2.15, 0.38, 0.17, 5, PURE, y=Y1 - 0.02, rot=0.3),
        star(4.6, 1.3, 0.7, 0.45, 12, BLACK, y=Y1 - 0.004, rot=0.1), star(4.6, 1.3, 0.56, 0.36, 12, PURE, y=Y1 - 0.016, rot=0.1),
        star(8.0, 2.2, 0.35, 0.16, 5, BLACK, y=Y1 - 0.004),
        star(0.2, 1.6, 0.9, 0.55, 14, RED, x=X0 + 0.004, rot=0.2), star(0.2, 1.6, 0.7, 0.42, 14, PURE, x=X0 + 0.016, rot=0.2)]
# 挂钟（后墙左段）：表盘在 env 里，指针单独导出
CLK = (-6.0, Y1 - 0.03, 1.95)
env.append(mk("cyl", (CLK[0], CLK[1] + 0.01, CLK[2]), (0.36, 0.05), MO, rot=(math.pi / 2, 0, 0), verts=28))
env.append(mk("cyl", (CLK[0], CLK[1] - 0.012, CLK[2]), (0.31, 0.03), PAPER2, rot=(math.pi / 2, 0, 0), verts=28))
for k in range(4):
    ang = k * math.pi / 2
    env.append(mk("box", (CLK[0] + 0.25 * math.cos(ang), CLK[1] - 0.03, CLK[2] + 0.25 * math.sin(ang)), (0.05, 0.01, 0.05), MO, smooth=False))
hand_m = mk("box", (CLK[0], CLK[1] - 0.045, CLK[2] + 0.11), (0.035, 0.012, 0.24), MO, smooth=False); hand_m.name = "hand_m"; hand_m.data.name = "hand_m"
hand_h = mk("box", (CLK[0] + 0.07, CLK[1] - 0.04, CLK[2]), (0.16, 0.012, 0.045), ZHU, smooth=False); hand_h.name = "hand_h"; hand_h.data.name = "hand_h"
set_origin(hand_m, CLK); set_origin(hand_h, CLK)
bpy.context.view_layer.update(); pivotize(hand_m); pivotize(hand_h)
env.append(mk("cyl", (CLK[0], CLK[1] - 0.055, CLK[2]), (0.035, 0.02), MO, rot=(math.pi / 2, 0, 0), verts=10))
# 一串小三角旗（后墙上沿），每面旗单独导出，网页里轻轻飘
env.append(mk("box", ((X0 + 2.0 + X1 - 1.0) / 2, Y1 - 0.04, 2.6), (X1 - X0 - 3.0, 0.015, 0.018), MO, smooth=False))
pens = []
FC = [BLACK, PURE, BLACK, PURE]
NPEN = 14 if not SLOTS else int((X1 - X0 - 3.4) / 1.55) + 1
for k in range(NPEN):
    px_ = X0 + 2.4 + k * 1.55; col = FC[k % 4]
    me = bpy.data.meshes.new("pen"); t = 0.012
    vs = [(-0.2, 0, 0), (0.2, 0, 0), (0, 0, -0.34), (-0.2, -t, 0), (0.2, -t, 0), (0, -t, -0.34)]
    me.from_pydata(vs, [], [(0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)]); me.update()
    o = bpy.data.objects.new(f"pen_{k + 1:02d}", me); sc.collection.objects.link(o); paint(o, col)
    o.location = (px_, Y1 - 0.05, 2.6); o.data.name = o.name; bpy.context.view_layer.update(); pens.append(pivotize(o))
# 右侧地毯（14 工位大舞台）
if not SLOTS:
    env.append(mk("box", (RUG_X, 0.35, 0.021), (4.0, 7.4, 0.012), RED, smooth=False))
    env.append(mk("box", (RUG_X, 0.35, 0.027), (3.6, 7.0, 0.012), BLACK, smooth=False))
# 流程线：墨黑虚线 + 箭头（从 1 号位出发 → 后排左→右 → 前排右→左 → 回到 1 号位）
path = [(-8.0, 0.55), (-6.8, 0.55), (-6.8, 1.45), (8.2, 1.45), (8.2, -2.45), (-6.8, -2.45), (-6.8, -0.35), (-8.0, -0.35)]
if SLOTS: path = [(-6.2, 1.45), (8.0, 1.45), (8.0, -2.45), (-6.2, -2.45), (-6.2, 1.45)]
dash, gap = 0.26, 0.2
for (ax, ay), (bx, by) in zip(path, path[1:]):
    L_ = math.hypot(bx - ax, by - ay); ux, uy = (bx - ax) / L_, (by - ay) / L_; t = 0.0
    while t < L_ - 0.05:
        e = min(L_, t + dash); m = (t + e) / 2
        env.append(mk("box", (ax + ux * m, ay + uy * m, 0.023), (abs(ux) * (e - t) + abs(uy) * 0.07, abs(uy) * (e - t) + abs(ux) * 0.1, 0.012), RED, smooth=False))
        t += dash + gap
def arrow(x, y, ux, uy):
    px, py = -uy, ux; L_, W_ = 0.42, 0.26
    pts = [(x + ux * L_, y + uy * L_), (x + px * W_, y + py * W_), (x - px * W_, y - py * W_)]
    me = bpy.data.meshes.new("arr"); vs = [(p[0], p[1], 0.034) for p in pts] + [(p[0], p[1], 0.018) for p in pts]
    me.from_pydata(vs, [], [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)]); me.update()
    o = bpy.data.objects.new("arr", me); sc.collection.objects.link(o); paint(o, RED); return o
if SLOTS:
    env += [arrow(-2.1, 1.45, 1, 0), arrow(2.1, 1.45, 1, 0), arrow(8.0, -0.5, 0, -1), arrow(4.2, -2.45, -1, 0), arrow(0.0, -2.45, -1, 0), arrow(-6.2, -0.5, 0, 1)]
else:
    env += [arrow(-7.5, 0.55, 1, 0), arrow(-1.4, 1.45, 1, 0), arrow(4.2, 1.45, 1, 0), arrow(8.2, -0.6, 0, -1),
            arrow(1.4, -2.45, -1, 0), arrow(-4.2, -2.45, -1, 0), arrow(-7.7, -0.35, -1, 0)]
# 工位
desks = []
for i, b in enumerate(ROSTER):
    n = i + 1; x, y = POS[i]
    dp = grow(desk(x, y, COLORS[i], big=(n == 1 and not SLOTS)) + desk_prop(PROPS[i], x, y, COLORS[i]), x, y, D)
    if is_back(i):
        for o in dp: o.location.z += RISE
    if a.robots: desks.append(join(dp, f"desk_{n:02d}")); set_origin(desks[-1], (x, y, 0))
    else: env += dp
envo = join(env, "env")
bots = [robot(i + 1, POS[i][0], POS[i][1] + (0.6 if (i == 0 and not SLOTS) else 0.52), COLORS[i], PROPS[i]) for i in range(len(ROSTER))]
for i in range(len(ROSTER)):
    if is_back(i): bots[i].location.z += RISE

# ---------- 灯光 / 相机（方向图：卡通 BSDF 两档硬明暗 + 零角度太阳＝硬阴影 + 透视低机位 + 透明底） ----------
sc.render.engine = "CYCLES"; sc.cycles.samples = a.samples; sc.cycles.use_denoising = True
sc.cycles.device = "CPU"; sc.render.film_transparent = True
sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = lin("#FFFFFF"); w.node_tree.nodes["Background"].inputs[1].default_value = 0.55
bpy.ops.object.light_add(type="SUN", rotation=(math.radians(52), 0, math.radians(-62))); sun = bpy.context.object
sun.data.energy = 3.2; sun.data.angle = 0.0
if a.render:   # 方向图专用：把材质换成卡通 BSDF（硬分层）
    toon = nt.nodes.new("ShaderNodeBsdfToon"); toon.component = "DIFFUSE"; toon.inputs["Size"].default_value = 0.9; toon.inputs["Smooth"].default_value = 0.0
    nt.links.new(ca.outputs["Color"], toon.inputs["Color"])
    mix = nt.nodes.new("ShaderNodeAddShader"); em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = 0.42
    nt.links.new(ca.outputs["Color"], em.inputs["Color"])
    nt.links.new(toon.outputs[0], mix.inputs[0]); nt.links.new(em.outputs[0], mix.inputs[1])
    nt.links.new(mix.outputs[0], nt.nodes["Material Output"].inputs["Surface"])

def camera(target, dirv, scale, persp_fov=0.0, dist=30.0):
    bpy.ops.object.camera_add(); cam = bpy.context.object; sc.camera = cam
    if persp_fov: cam.data.type = "PERSP"; cam.data.sensor_fit = "HORIZONTAL"; cam.data.angle = math.radians(persp_fov)
    else: cam.data.type = "ORTHO"; cam.data.ortho_scale = scale
    d = Vector(dirv).normalized(); cam.location = Vector(target) + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    return cam

def freestyle(px=2.2):
    sc.render.use_freestyle = True; sc.render.line_thickness_mode = "ABSOLUTE"; sc.render.line_thickness = px
    fs = bpy.context.view_layer.freestyle_settings
    ls = fs.linesets[0] if len(fs.linesets) else fs.linesets.new("ink")
    if ls.linestyle is None: ls.linestyle = bpy.data.linestyles.new("ink")
    ls.select_by_visibility = True; ls.select_crease = True; ls.select_silhouette = True; ls.select_border = True; ls.select_external_contour = True
    ls.linestyle.color = lin(MO)[:3]; ls.linestyle.thickness = px

if a.render:
    rx, ry = map(int, a.res.split("x")); sc.render.resolution_x, sc.render.resolution_y = rx, ry
    camera((1.1, 0.1, 0.7), (0.16, -1.0, 0.56), 0, persp_fov=40, dist=36); freestyle(2.6)
    sc.render.filepath = os.path.abspath(a.render); bpy.ops.render.render(write_still=True)

if a.robots:
    # 全家福：每个机器人连同自己的工位，排成 2 排 × 7，单独渲染；名字由 tools 脚本另外排版
    from bpy_extras.object_utils import world_to_camera_view
    for o in bpy.data.objects:
        if o.name == "env" or o.name.startswith(("pen_", "hand_")): o.hide_render = True
    for i, (b, d) in enumerate(zip(bots, desks)):
        col_, row = i % 7, i // 7
        ox, oy = col_ * 2.05 - 6.15, 40 + row * 4.4
        dx, dy = ox - d.location.x, oy - d.location.y
        d.location = (ox, oy, 0); b.location = (b.location.x + dx, b.location.y + dy, 0)
    bpy.ops.mesh.primitive_plane_add(size=80, location=(0, 40, 0)); pl = bpy.context.object; paint(pl, PAPER)
    sc.render.resolution_x, sc.render.resolution_y = 2000, 1300
    cam = camera((0, 42.2, 0.2), (0.0, -1.0, 0.85), 15.6); freestyle(2.2)
    bpy.context.view_layer.update()
    pts = []
    for i, d in enumerate(desks):
        v = world_to_camera_view(sc, cam, d.matrix_world @ Vector((0, -0.55, 0)))
        pts.append([ROSTER[i]["short"], round(v.x * 2000), round((1 - v.y) * 1300)])
    json.dump(pts, open(os.path.abspath(a.robots) + ".json", "w"), ensure_ascii=False)
    sc.render.filepath = os.path.abspath(a.robots); bpy.ops.render.render(write_still=True)

if a.export:
    bpy.ops.object.select_all(action="DESELECT")
    for o in bpy.data.objects:
        if o.type in ("MESH", "EMPTY"): o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=os.path.abspath(a.export), export_format="GLB", use_selection=True,
                              export_apply=True, export_yup=True, export_draco_mesh_compression_enable=False,
                              export_vertex_color="MATERIAL", export_normals=True, export_texcoords=False, export_materials="EXPORT")
    print("exported", a.export, os.path.getsize(a.export))

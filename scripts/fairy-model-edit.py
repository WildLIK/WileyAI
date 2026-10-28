"""Rebuild Fairy_Assistant.vrm from the original: live hair/skirt, reference colours, new details.

blender -b --python scripts/fairy-model-edit.py -- <model-0.15.vrm> <out.vrm> [steps]
Requires Blender 5.2 with the VRM Add-on for Blender (extensions.blender.org: vrm).
steps: comma list of physics,colors,details (default: all)
"""
import bpy, bmesh, math, sys
import numpy as np
from mathutils import Vector, Matrix

args = sys.argv[sys.argv.index("--") + 1:]
SRC, DST = args[0], args[1]
STEPS = set((args[2] if len(args) > 2 else "physics,colors,details").split(","))

bpy.ops.wm.read_homefile(use_empty=True)
bpy.ops.import_scene.vrm(filepath=SRC)
ARM = next(o for o in bpy.data.objects if o.type == "ARMATURE")
SB = ARM.data.vrm_addon_extension.spring_bone1
MW = ARM.matrix_world


def bone_head(name):
    return np.array(MW @ ARM.data.bones[name].head_local)


def bone_tail(name):
    return np.array(MW @ ARM.data.bones[name].tail_local)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def world_coords(obj):
    m = np.array(obj.matrix_world)
    co = np.array([v.co for v in obj.data.vertices])
    return co @ m[:3, :3].T + m[:3, 3]


def set_weights(obj, rows, limit=4):
    """rows: list of dict bone->weight per vertex (only vertices to change)."""
    groups = {g.name: g for g in obj.vertex_groups}
    for index, weights in rows:
        top = sorted(weights.items(), key=lambda kv: -kv[1])[:limit]
        total = sum(w for _, w in top) or 1
        # Clear every existing influence of the vertex, then write the new set.
        for g in obj.data.vertices[index].groups:
            obj.vertex_groups[g.group].remove([index])
        for name, w in top:
            if w / total > 1e-4:
                groups[name].add([index], w / total, "REPLACE")


def closest_on_polyline(points, p):
    """Return (distance, segment index, arc parameter 0..1 along the whole polyline)."""
    lengths = np.linalg.norm(np.diff(points, axis=0), axis=1)
    total = lengths.sum()
    best = (1e9, 0, 0.0)
    walked = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        ab = b - a
        u = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
        d = np.linalg.norm(a + ab * u - p)
        if d < best[0]:
            best = (d, i, (walked + u * lengths[i]) / total)
        walked += lengths[i]
    return best


# ---------------------------------------------------------------- physics
def physics():
    hair = bpy.data.objects["Hair"]
    chains = []
    for k in range(1, 10):
        names = [f"J_Sec_Hair1_{k:02d}", f"J_Sec_Hair2_{k:02d}", f"J_Sec_Hair3_{k:02d}", f"J_Sec_Hair3_{k:02d}_end"]
        points = np.array([bone_head(n) for n in names] + [bone_tail(names[-1])])
        chains.append((names, points))
    co = world_coords(hair)
    rows = []
    for index, p in enumerate(co):
        hits = sorted((closest_on_polyline(points, p) + (names,) for names, points in chains), key=lambda h: h[0])[:2]
        # The scalp stays on the head; strands loosen toward their ends.
        d0 = hits[0][0]
        w0 = 1 / max(hits[0][0], 0.004) ** 2
        w1 = 1 / max(hits[1][0], 0.004) ** 2 if hits[1][0] < d0 * 1.8 else 0
        weights = {"J_Bip_C_Head": 0.0}
        influence = 0.0
        for (d, seg, t, names), w in ((hits[0], w0), (hits[1], w1)):
            if not w:
                continue
            share = w / (w0 + w1)
            a = float(smoothstep(0.12, 0.62, t)) * share
            influence += a
            weights[names[seg]] = weights.get(names[seg], 0) + a
        weights["J_Bip_C_Head"] = max(0.0, 1 - influence)
        rows.append((index, weights))
    set_weights(hair, rows)
    print("hair weighted", len(rows))

    # Skirt: VRoid's thigh chains become hip chains, so the skirt sways and
    # is pushed by the leg colliders instead of rotating rigidly with a thigh.
    bpy.context.view_layer.objects.active = ARM
    bpy.ops.object.mode_set(mode="EDIT")
    eb = ARM.data.edit_bones
    skirt_chains = {
        "FrontL": "J_Sec_L_TopsUpperLegFront_01", "SideL": "J_Sec_L_TopsUpperLegSide_01", "BackL": "J_Sec_L_TopsUpperLegBack_01",
        "BackR": "J_Sec_R_TopsUpperLegBack_01", "SideR": "J_Sec_R_TopsUpperLegSide_01", "FrontR": "J_Sec_R_TopsUpperLegFront_01",
    }
    for name in skirt_chains.values():
        eb[name].use_connect = False
        eb[name].parent = eb["J_Bip_C_Hips"]
    bpy.ops.object.mode_set(mode="OBJECT")
    skirt = bpy.data.objects["Fairy_Responsive_Skirt"]
    centre = (bone_head("J_Bip_L_UpperLeg") + bone_head("J_Bip_R_UpperLeg")) / 2
    azimuth = {}
    for key, name in skirt_chains.items():
        h = bone_head(name) - centre
        azimuth[name] = math.atan2(h[0], -h[1])
    order = sorted(azimuth, key=azimuth.get)
    co = world_coords(skirt)
    top, hem = co[:, 2].max(), co[:, 2].min()
    rows = []
    for index, p in enumerate(co):
        theta = math.atan2(p[0] - centre[0], -(p[1] - centre[1]))
        # Two neighbouring chains around the waist, blended by angle.
        diffs = [((theta - azimuth[n] + math.pi) % (2 * math.pi)) - math.pi for n in order]
        ranked = sorted(range(len(order)), key=lambda i: abs(diffs[i]))[:2]
        a0, a1 = abs(diffs[ranked[0]]), abs(diffs[ranked[1]])
        s0 = a1 / (a0 + a1) if a0 + a1 > 1e-6 else 1
        # The waistband stays on the hips; the hem follows the springs.
        influence = float(smoothstep(top - 0.02, hem + 0.03, p[2])) * 0.85
        weights = {"J_Bip_C_Hips": 1 - influence,
                   order[ranked[0]]: influence * s0,
                   order[ranked[1]]: influence * (1 - s0)}
        rows.append((index, weights))
    set_weights(skirt, rows)
    print("skirt weighted", len(rows))

    for spring in SB.springs:
        names = [j.node.bone_name for j in spring.joints]
        if any(n.startswith("J_Sec_Hair") for n in names):
            for j in spring.joints:
                j.drag_force = 0.45
                j.gravity_power = 0.03
                j.gravity_dir = (0, 0, -1)
        if names and names[0] in skirt_chains.values():
            for j in spring.joints:
                j.stiffness = 1.1
                j.drag_force = 0.5
                j.gravity_power = 0.08
                j.gravity_dir = (0, 0, -1)
                j.hit_radius = 0.022


if "physics" in STEPS:
    physics()


# ---------------------------------------------------------------- colours
def mtoon(name):
    return bpy.data.materials[name].vrm_addon_extension.mtoon1


def recolor_texture(material, tint, keep=0.25, lift=0.55):
    """Desaturate the base texture toward a pale `tint`, keeping alpha and some detail."""
    info = mtoon(material).pbr_metallic_roughness.base_color_texture.index
    image = info.source
    if image is None:
        return
    px = np.array(image.pixels[:], dtype=np.float32).reshape(-1, 4)
    luminance = px[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    grey = np.repeat(luminance[:, None], 3, axis=1)
    pale = grey + (1 - grey) * lift
    rgb = (pale * (1 - keep) + px[:, :3] * keep) * np.array(tint, dtype=np.float32)
    px[:, :3] = np.clip(rgb, 0, 1)
    image.pixels.foreach_set(px.ravel())
    image.update()
    image.pack()
    print("recoloured", material, image.name, image.size[:])


def set_color(material, base, shade):
    m = mtoon(material)
    m.pbr_metallic_roughness.base_color_factor = (*base, m.pbr_metallic_roughness.base_color_factor[3])
    m.extensions.vrmc_materials_mtoon.shade_color_factor = shade


def colors():
    # Reference: black ribbons, sash and back bow on a white dress.
    for name in ("V9 muted blue-grey satin", "V9 charcoal-blue ribbon"):
        set_color(name, (0.035, 0.035, 0.045), (0.012, 0.012, 0.018))
    # White skirt petals with a faint ice-blue cast instead of lilac.
    recolor_texture("V11 embroidered blue-lilac petal satin", (0.96, 0.98, 1.0), keep=0.2, lift=0.6)
    set_color("V11 embroidered blue-lilac petal satin", (1, 1, 1), (0.78, 0.84, 0.95))
    # Pale, cool, translucent wings (reference: white-blue membrane).
    recolor_texture("V9 translucent pearl-lilac wing membrane", (0.9, 0.96, 1.0), keep=0.3, lift=0.5)
    set_color("V9 translucent pearl-lilac wing membrane", (0.97, 0.99, 1.0), (0.78, 0.86, 0.97))


if "colors" in STEPS:
    colors()


# ---------------------------------------------------------------- details
BLACK = "V9 charcoal-blue ribbon"


def skinned(obj, bone, material=BLACK):
    """Parent a new mesh to the armature, fully weighted to one bone."""
    obj.data.materials.clear()
    obj.data.materials.append(bpy.data.materials[material])
    group = obj.vertex_groups.new(name=bone)
    group.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    obj.parent = ARM
    obj.matrix_parent_inverse = ARM.matrix_world.inverted()
    mod = obj.modifiers.new("Armature", "ARMATURE")
    mod.object = ARM
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def join(objects, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = obj.data.name = name
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def garter():
    # Right thigh just below the skirt hem (measured cross-section at 0.68 m).
    cx, cy, cz = -0.0811, 0.0018, 0.672
    rx, ry = 0.0585, 0.066
    band_h, thick, segments = 0.013, 0.0035, 64
    mesh = bpy.data.meshes.new("Garter")
    bm = bmesh.new()
    rings = []
    for z, grow in ((cz - band_h / 2, 0), (cz + band_h / 2, 0), (cz + band_h / 2, thick), (cz - band_h / 2, thick)):
        ring = []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            ring.append(bm.verts.new((cx + (rx + grow) * math.cos(a), cy + (ry + grow) * math.sin(a), z)))
        rings.append(ring)
    for r in range(4):
        a_ring, b_ring = rings[r], rings[(r + 1) % 4]
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((a_ring[i], a_ring[j], b_ring[j], b_ring[i]))
    bm.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    band = bpy.data.objects.new("Garter", mesh)
    bpy.context.collection.objects.link(band)

    # Bow on the outer front of the thigh, facing outward-forward.
    angle = math.radians(235)  # -x outer, -y front
    nx, ny = math.cos(angle), math.sin(angle)
    px, py = cx + (rx + thick + 0.006) * nx, cy + (ry + thick + 0.006) * ny
    parts = []
    for side in (-1, 1):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.019, minor_radius=0.0052, major_segments=24, minor_segments=8)
        loop = bpy.context.active_object
        loop.scale = (1.0, 0.55, 0.42)
        loop.location = (side * 0.019, 0, 0.003)
        loop.rotation_euler = (0, side * math.radians(-18), 0)
        parts.append(loop)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0085, segments=12, ring_count=8)
    knot = bpy.context.active_object
    knot.scale = (1.0, 0.8, 1.1)
    parts.append(knot)
    for side in (-1, 1):
        bpy.ops.mesh.primitive_cube_add(size=1)
        tail = bpy.context.active_object
        tail.scale = (0.011, 0.003, 0.04)
        tail.location = (side * 0.011, 0, -0.022)
        tail.rotation_euler = (0, side * math.radians(-16), 0)
        parts.append(tail)
    bow = join(parts, "GarterBow")
    # Local bow plane is XZ facing -Y; turn it to face the thigh normal.
    bow.rotation_euler = (0, 0, math.atan2(nx, -ny))
    bow.location = (px, py, cz)
    bpy.ops.object.select_all(action="DESELECT")
    bow.select_set(True)
    bpy.context.view_layer.objects.active = bow
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    garter = join([band, bow], "Fairy_Garter")
    skinned(garter, "J_Bip_R_UpperLeg")
    print("garter", len(garter.data.vertices))


def heels():
    costume = bpy.data.objects["Fairy_Costume_and_Wings"]
    black_slot = next(i for i, s in enumerate(costume.material_slots) if s.material and s.material.name == BLACK)
    me = costume.data
    feet = {costume.vertex_groups[f"J_Bip_{s}_{b}"].index for s in "LR" for b in ("Foot", "ToeBase")}
    in_foot = np.zeros(len(me.vertices), bool)
    for v in me.vertices:
        if any(g.group in feet and g.weight >= 0.5 for g in v.groups):
            in_foot[v.index] = True
    z = np.array([v.co.z for v in me.vertices])  # mesh is at the origin with identity transform
    xs = np.array([v.co.x for v in me.vertices])
    changed = 0
    for p in me.polygons:
        idx = list(p.vertices)
        # The flat sole band of each boot becomes black, as on the reference.
        # The periwinkle sole band (up to 4 cm) becomes black, as on the reference.
        if z[idx].max() < 0.045 and np.all(np.abs(xs[idx]) > 0.02) and costume.material_slots[p.material_index].name == "V9 pale periwinkle stitching":
            p.material_index = black_slot
            changed += 1
    print("sole faces", changed)
    for side, x in (("L", 0.0772), ("R", -0.0772)):
        bpy.ops.mesh.primitive_cube_add(size=1)
        heel = bpy.context.active_object
        heel.name = heel.data.name = f"Fairy_Heel_{side}"
        heel.scale = (0.04, 0.045, 0.038)
        heel.location = (x, 0.044, -0.015)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        # Taper toward the ground like a block heel.
        for v in heel.data.vertices:
            if v.co.z < -0.025:
                v.co.x = x + (v.co.x - x) * 0.82
                v.co.y = 0.048 + (v.co.y - 0.044) * 0.78
        skinned(heel, f"J_Bip_{side}_Foot")
    print("heels added")


if "details" in STEPS:
    garter()
    heels()

ARM.data.vrm_addon_extension.vrm1.meta.version = "0.16"

# Export
for o in bpy.data.objects:
    o.select_set(True)
bpy.context.view_layer.objects.active = ARM
print("EXPORT", bpy.ops.export_scene.vrm(filepath=DST))

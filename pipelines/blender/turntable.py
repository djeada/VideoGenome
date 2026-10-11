"""Product turntable for VideoGenome's render_3d capability (Blender 3.6+).

Two ways to run it:

  Direct:   blender -b --factory-startup --python turntable.py -- \
                --output out.mp4 --width 1080 --height 1080 --fps 24 --seconds 4 \
                [--model product.glb] [--still] [--engine eevee|cycles|workbench]
  Via MCP:  blender-mcp-server's blender_python_exec(script_path=turntable.py,
                args={"output": ..., "width": ...}, transport="headless")

The model (glb/gltf/obj/fbx/stl/ply) is centred and scaled to a unit size; a
camera orbits 360 degrees under a three-point light rig. Frames are rendered
to PNG and encoded with FFmpeg, which avoids Blender-version differences in
video output settings. Without --model a labelled stand-in object is used.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile

import bpy
from mathutils import Vector


def _arguments() -> dict:
    # MCP headless transport injects ``args``; the CLI passes argv after "--".
    injected = globals().get("args")
    if isinstance(injected, dict):
        return dict(injected)
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parsed: dict = {}
    key = None
    for token in argv:
        if token.startswith("--"):
            key = token[2:].replace("-", "_")
            parsed[key] = True
        elif key:
            parsed[key] = token
            key = None
    return parsed


def _hex(value: str) -> tuple:
    """sRGB hex -> linear RGBA, which is what Blender colour sockets expect."""
    value = value.lstrip("#")
    srgb = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb) + (1.0,)


def _material(name: str, color: tuple, roughness: float = 0.45):
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    try:
        material.use_nodes = True  # Always on (and deprecated) in newer Blender.
    except AttributeError:
        pass
    bsdf = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = roughness
    return material


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import(path: str) -> list:
    before = set(bpy.data.objects)
    extension = os.path.splitext(path)[1].lower()
    if extension in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif extension == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif extension == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif extension == ".stl":
        bpy.ops.wm.stl_import(filepath=path)
    elif extension == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    else:
        raise SystemExit(f"turntable: unsupported model format {extension}")
    return [o for o in bpy.data.objects if o not in before]


def _stand_in() -> list:
    bpy.ops.mesh.primitive_monkey_add(size=1.6)
    obj = bpy.context.active_object
    obj.modifiers.new("smooth", "SUBSURF").levels = 2
    bpy.ops.object.shade_smooth()
    obj.data.materials.append(_material("stand_in", (0.85, 0.36, 0.2, 1.0), 0.35))
    return [obj]


def _normalise(objects: list) -> float:
    meshes = [o for o in objects if o.type == "MESH"]
    if not meshes:
        raise SystemExit("turntable: the model contains no mesh")
    bpy.context.view_layer.update()
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    low = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    high = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    size = max((high - low).length, 1e-6)
    pivot = bpy.data.objects.new("model_pivot", None)
    bpy.context.scene.collection.objects.link(pivot)
    for obj in objects:
        if obj.parent is None:
            obj.parent = pivot
    pivot.scale = (2.0 / size,) * 3
    centre = (low + high) / 2
    pivot.location = (-centre.x * 2.0 / size, -centre.y * 2.0 / size, -low.z * 2.0 / size)
    return (high.z - low.z) * 2.0 / size


def _engine(scene, name: str) -> str:
    candidates = {"eevee": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"], "cycles": ["CYCLES"],
                  "workbench": ["BLENDER_WORKBENCH"]}[name]
    for candidate in candidates:
        try:
            scene.render.engine = candidate
            return candidate
        except TypeError:
            continue
    raise SystemExit(f"turntable: engine {name} unavailable")


def main() -> None:
    options = _arguments()
    output = os.path.abspath(str(options["output"]))
    width, height = int(options.get("width", 1080)), int(options.get("height", 1080))
    fps = int(options.get("fps", 24))
    seconds = float(options.get("seconds", options.get("duration_seconds", 4)))
    still = str(options.get("still", "")).lower() in ("1", "true", "image") or options.get("still") is True
    frames = 1 if still else max(2, round(seconds * fps))

    _clear()
    scene = bpy.context.scene
    model = options.get("model")
    objects = _import(str(model)) if model else _stand_in()
    model_height = _normalise(objects)

    world = bpy.data.worlds.new("studio")
    background = _hex(str(options.get("background", "#1B1E24")))
    world.color = background[:3]
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    node = world.node_tree.nodes.get("Background") if world.node_tree else None
    if node:
        node.inputs["Color"].default_value = background
        node.inputs["Strength"].default_value = 0.35
    scene.world = world
    bpy.ops.mesh.primitive_plane_add(size=40)
    floor = bpy.context.active_object
    # The floor is the background colour, slightly lifted, so the stage reads as one
    # seamless studio sweep that matches the brand instead of a grey table.
    hexcode = str(options.get("background", "#1B1E24")).lstrip("#")
    floor_colour = options.get("floor") or "#{:02X}{:02X}{:02X}".format(
        *(min(255, round(int(hexcode[i:i + 2], 16) * 1.35 + 4)) for i in (0, 2, 4)))
    floor.data.materials.append(_material("floor", _hex(str(floor_colour)), 0.55))

    for name, location, energy, size in (("key", (3.5, -3.5, 4.5), 260, 2.5), ("fill", (-4.5, -2, 2.5), 70, 4),
                                         ("rim", (0, 4.5, 3.5), 420, 1.5)):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy, light_data.size = energy, size
        light = bpy.data.objects.new(name, light_data)
        light.location = location
        light.rotation_euler = (Vector((0, 0, 1)) - Vector(location)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(light)

    rig = bpy.data.objects.new("orbit", None)
    scene.collection.objects.link(rig)
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    camera.data.lens = 60
    camera.location = (0, -6.2, 1.2 + model_height * 0.6)
    camera.parent = rig
    scene.collection.objects.link(camera)
    track = camera.constraints.new("TRACK_TO")
    target = bpy.data.objects.new("target", None)
    target.location = (0, 0, model_height * 0.5)
    scene.collection.objects.link(target)
    track.target = target
    scene.camera = camera
    if not still:
        rig.rotation_euler = (0, 0, 0)
        rig.keyframe_insert("rotation_euler", index=2, frame=1)
        rig.rotation_euler = (0, 0, 2 * math.pi * frames / (frames + 1))
        rig.keyframe_insert("rotation_euler", index=2, frame=frames)
        for curve in getattr(rig.animation_data.action, "fcurves", []):
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"

    engine = _engine(scene, str(options.get("engine", "eevee")))
    if engine == "CYCLES":
        scene.cycles.samples = int(options.get("samples", 64))
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, frames
    scene.render.image_settings.file_format = "PNG"

    work = tempfile.mkdtemp(prefix="vg-turntable-")
    try:
        scene.render.filepath = os.path.join(work, "frame_")
        bpy.ops.render.render(animation=True)
        rendered = sorted(f for f in os.listdir(work) if f.endswith(".png"))
        if len(rendered) != frames:
            raise SystemExit(f"turntable: expected {frames} frames, rendered {len(rendered)}")
        if still:
            shutil.copyfile(os.path.join(work, rendered[0]), output)
        else:
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps),
                            "-i", os.path.join(work, "frame_%04d.png"), "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "18", output], check=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"turntable: wrote {output} ({frames} frames, {engine})")
    globals()["__result__"] = {"output": output, "frames": frames, "engine": engine}


main()

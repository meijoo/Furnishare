"""Warm Blender worker. Runs inside Blender and serves whitelisted structured commands on localhost.

  R2R_WORKER_TOKEN=<secret> blender --background --factory-startup --python worker.py -- \
      --port 0 --ready-file /path/worker.json [--allowed-root DIR ...] [--parent-pid PID]

Protocol: one TCP connection per request. The client sends one JSON line
  {"id": 1, "token": "...", "cmd": "create_room", "params": {...}}
and receives one JSON line
  {"id": 1, "ok": true, "result": {...}, "elapsed_ms": 12.3}  or  {"id": 1, "ok": false, "error": {"type", "message"}}

No Python is ever evaluated from requests; each command validates its params with blender_mcp.specs.
"""
from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import templates  # noqa: E402
from templates import specs  # noqa: E402
from blender_mcp import layout  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
MAX_REQUEST_BYTES = 1 << 20
FURNITURE_PREFIX = "obj:"


class CommandError(Exception):
    def __init__(self, type_: str, message: str):
        super().__init__(message)
        self.type = type_


def log(*args):
    print("[r2r-worker]", *args, file=sys.stderr, flush=True)


def _check(name, value, allowed, required=()):
    try:
        specs._check_keys(name, value, set(allowed), set(required))
    except specs.ValidationError as exc:
        raise CommandError("validation", str(exc))


class Worker:
    def __init__(self, allowed_roots: list[Path]):
        self.allowed_roots = [r.resolve() for r in allowed_roots]
        self.room: dict | None = None
        self.room_objects: list[str] = []
        self.objects: dict[str, dict] = {}
        self.commands = {
            "ping": self.ping,
            "reset_scene": self.reset_scene,
            "create_room": self.create_room,
            "instantiate_furniture": self.instantiate_furniture,
            "set_dimensions_and_material": self.set_dimensions_and_material,
            "set_transform": self.set_transform,
            "remove_object": self.remove_object,
            "list_objects": self.list_objects,
            "validate_scene": self.validate_scene,
            "render_preview": self.render_preview,
            "export_asset": self.export_asset,
            "build_asset": self.build_asset,
            "measure_asset": self.measure_asset,
        }
        templates.reset_blend()

    # ------------------------------------------------------------ helpers

    def _path(self, value, suffixes) -> Path:
        if not isinstance(value, str) or not os.path.isabs(value):
            raise CommandError("validation", "path must be an absolute path string")
        p = Path(value)
        specs.filename(p.name, suffixes)
        parent = p.parent.resolve()
        if not any(parent == r or parent.is_relative_to(r) for r in self.allowed_roots):
            raise CommandError("forbidden", f"path is outside the allowed output roots: {[str(r) for r in self.allowed_roots]}")
        parent.mkdir(parents=True, exist_ok=True)
        return parent / p.name

    def _obj(self, object_id) -> dict:
        oid = specs.object_id(object_id)
        if oid not in self.objects:
            raise CommandError("not_found", f"no object with id {oid!r}")
        return self.objects[oid]

    def _bobj(self, entry) -> bpy.types.Object:
        return bpy.data.objects[entry["blender_name"]]

    @staticmethod
    def _apply_transform(obj, position_m, rotation_y_rad):
        x, y, z = position_m
        obj.location = (x, -z, y)          # scene (Y-up, +Z front) -> Blender (Z-up, -Y front)
        obj.rotation_euler = (0.0, 0.0, rotation_y_rad)

    def _scene_object(self, oid) -> dict:
        e = self.objects[oid]
        return {"object_id": oid, "category": e["spec"]["category"], "position_m": e["position_m"],
                "rotation_y_rad": e["rotation_y_rad"], "dimensions_m": e["spec"]["dimensions_m"],
                "color_hex": e["spec"]["color_hex"], "material": e["spec"]["material"], "shape": e["spec"]["shape"],
                "texture": e["spec"].get("texture"), "form": e["spec"].get("form") or {}}

    def _rebuild(self, oid, spec):
        entry = self.objects.get(oid)
        if entry is not None:
            templates.remove_objects([self._bobj(entry)])
        obj, _ = templates.build_furniture(spec, name=FURNITURE_PREFIX + oid)
        return obj

    # ------------------------------------------------------------ commands

    def ping(self, params):
        _check("params", params, ())
        return {"pong": True, "blender": bpy.app.version_string, "pid": os.getpid(),
                "template_version": specs.TEMPLATE_VERSION, "features": list(specs.WORKER_FEATURES),
                "objects": len(self.objects), "room": self.room is not None}

    def reset_scene(self, params):
        _check("params", params, ())
        templates.reset_blend()
        self.room, self.room_objects, self.objects = None, [], {}
        return {"reset": True}

    def create_room(self, params):
        room = specs.room_spec(params)
        if self.room_objects:
            templates.remove_objects([bpy.data.objects[n] for n in self.room_objects if n in bpy.data.objects])
        objs = templates.build_room(room)
        self.room, self.room_objects = room, [o.name for o in objs]
        lo, hi = templates.room_expected_bbox(room)
        return {"room": room, "objects": self.room_objects, "outer_bbox_m": {"min": lo, "max": hi}}

    def instantiate_furniture(self, params):
        _check("params", params, ("object_id", "spec", "position_m", "rotation_y_rad", "product_id"),
               ("object_id", "spec"))
        oid = specs.object_id(params["object_id"])
        if oid in self.objects:
            raise CommandError("conflict", f"object {oid!r} already exists; use set_dimensions_and_material")
        if len(self.objects) >= 64:
            raise CommandError("limit", "scene is limited to 64 furniture objects")
        spec = specs.furniture_spec(params["spec"])
        pos = specs.position(params.get("position_m", [0.0, 0.0, 0.0]))
        rot = specs.rotation(params.get("rotation_y_rad", 0.0))
        pid = params.get("product_id")
        if pid is not None and (not isinstance(pid, str) or len(pid) > 200):
            raise CommandError("validation", "product_id must be a string of at most 200 chars")
        obj = self._rebuild(oid, spec)
        self._apply_transform(obj, pos, rot)
        self.objects[oid] = {"spec": spec, "position_m": pos, "rotation_y_rad": rot,
                             "blender_name": obj.name, "product_id": pid}
        return self._scene_object(oid)

    def set_dimensions_and_material(self, params):
        """texture {path?, mode?, tile_m?} is merged into the current texture (path required if there is none);
        clear_texture: true removes it. form replaces the current form ({} clears it)."""
        _check("params", params, ("object_id", "dimensions_m", "color_hex", "material", "frame_finish", "shape",
                                  "texture", "clear_texture", "form"), ("object_id",))
        entry = self._obj(params["object_id"])
        oid = specs.object_id(params["object_id"])
        merged = dict(entry["spec"])
        for key in ("dimensions_m", "color_hex", "material", "frame_finish", "shape", "form"):
            if params.get(key) is not None:
                merged[key] = params[key]
        if params.get("clear_texture") not in (None, False, True):
            raise CommandError("validation", "clear_texture must be a boolean")
        if params.get("clear_texture"):
            if params.get("texture") is not None:
                raise CommandError("validation", "pass either texture or clear_texture, not both")
            merged.pop("texture", None)
        elif params.get("texture") is not None:
            if not isinstance(params["texture"], dict):
                raise CommandError("validation", "texture must be an object")
            merged["texture"] = dict(merged.get("texture") or {}, **params["texture"])
        spec = specs.furniture_spec(merged)
        obj = self._rebuild(oid, spec)
        self._apply_transform(obj, entry["position_m"], entry["rotation_y_rad"])
        entry.update(spec=spec, blender_name=obj.name)
        return self._scene_object(oid)

    def set_transform(self, params):
        _check("params", params, ("object_id", "position_m", "rotation_y_rad"), ("object_id",))
        entry = self._obj(params["object_id"])
        if "position_m" in params:
            entry["position_m"] = specs.position(params["position_m"])
        if "rotation_y_rad" in params:
            entry["rotation_y_rad"] = specs.rotation(params["rotation_y_rad"])
        self._apply_transform(self._bobj(entry), entry["position_m"], entry["rotation_y_rad"])
        return self._scene_object(specs.object_id(params["object_id"]))

    def remove_object(self, params):
        _check("params", params, ("object_id",), ("object_id",))
        entry = self._obj(params["object_id"])
        templates.remove_objects([self._bobj(entry)])
        del self.objects[params["object_id"]]
        return {"removed": params["object_id"]}

    def list_objects(self, params):
        _check("params", params, ())
        return {"room": self.room, "objects": [self._scene_object(o) for o in self.objects]}

    def validate_scene(self, params):
        _check("params", params, ())
        return layout.validate_scene(self.room, [self._scene_object(o) for o in self.objects])

    def _targets(self, target):
        if target == "scene":
            names = self.room_objects + [e["blender_name"] for e in self.objects.values()]
        elif target == "room":
            if not self.room_objects:
                raise CommandError("not_found", "no room has been created")
            names = list(self.room_objects)
        else:
            names = [self._obj(target)["blender_name"]]
        objs = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
        if not objs:
            raise CommandError("not_found", "nothing to export or render")
        return objs

    def export_asset(self, params):
        _check("params", params, ("target", "path", "format"), ("target", "path"))
        fmt = params.get("format", "usdz")
        if fmt not in specs.EXPORT_FORMATS:
            raise CommandError("validation", f"format must be one of {specs.EXPORT_FORMATS}")
        path = self._path(params["path"], ("." + fmt,))
        target = params["target"]
        objs = self._targets(target)
        single = target not in ("scene", "room")
        saved = [(o, o.matrix_world.copy()) for o in objs] if single else []
        try:
            if single:
                objs[0].matrix_world = Matrix.Identity(4)  # assets are exported in canonical pose at the origin
                bpy.context.view_layer.update()
            (templates.export_usdz if fmt == "usdz" else templates.export_glb)(objs, path)
        finally:
            for o, m in saved:
                o.matrix_world = m
        result = {"path": str(path), "format": fmt, "target": target, "bytes": path.stat().st_size}
        if fmt == "usdz":
            measured = templates.measure_usd(path)
            result["measured_bbox_m"] = measured
            if single:
                spec = self._obj(target)["spec"]
                result["max_abs_error_m"] = templates.bbox_error(measured, templates.furniture_expected_bbox(spec))
            elif target == "room":
                result["max_abs_error_m"] = templates.bbox_error(measured, templates.room_expected_bbox(self.room))
        return result

    def measure_asset(self, params):
        _check("params", params, ("path",), ("path",))
        path = self._path(params["path"], (".usdz", ".usd", ".usdc", ".usda"))
        if not path.is_file():
            raise CommandError("not_found", f"{path.name} does not exist")
        return templates.measure_usd(path)

    def build_asset(self, params):
        """Builds a standalone asset at the origin without touching the interactive scene."""
        _check("params", params, ("spec", "room", "usdz_path", "glb_path", "report_parts"), ("usdz_path",))
        if ("spec" in params) == ("room" in params):
            raise CommandError("validation", "pass exactly one of spec or room")
        if params.get("report_parts", False) not in (True, False):
            raise CommandError("validation", "report_parts must be a boolean")
        usdz = self._path(params["usdz_path"], (".usdz",))
        glb = self._path(params["glb_path"], (".glb",)) if params.get("glb_path") else None
        if "room" in params:
            spec, kind = specs.room_spec(params["room"]), "room"
        else:
            spec, kind = specs.furniture_spec(params["spec"]), "furniture"
        result = templates.build_and_export(spec, usdz, glb, kind=kind, report_parts=bool(params.get("report_parts")))
        result["spec"] = spec
        return result

    def render_preview(self, params):
        _check("params", params, ("path", "width_px", "height_px", "engine", "view", "cutaway", "target"), ("path",))
        path = self._path(params["path"], (".png",))
        opts = specs.render_params({k: v for k, v in params.items() if k != "path"})
        objs = self._targets(opts["target"])
        scene = bpy.context.scene
        hidden = []
        if opts["cutaway"] and opts["view"] != "top":
            for name in ("room_wall_front", "room_wall_right"):
                o = bpy.data.objects.get(name)
                if o is not None and o in objs:
                    hidden.append(o)
        visible = set(objs) - set(hidden)
        prior = {o: o.hide_render for o in scene.objects}
        for o in scene.objects:
            if o.type == "MESH":
                o.hide_render = o not in visible
        cam, sun = self._camera(scene, list(visible), opts["view"], opts["width_px"] / opts["height_px"])
        try:
            r = scene.render
            r.engine = "BLENDER_WORKBENCH" if opts["engine"] == "workbench" else "BLENDER_EEVEE"
            r.resolution_x, r.resolution_y, r.resolution_percentage = opts["width_px"], opts["height_px"], 100
            r.image_settings.file_format = "PNG"
            r.film_transparent = False
            if opts["engine"] == "workbench":
                sh = scene.display.shading
                textured = any(m is not None and m.get("r2r_uv_mode") for o in visible if o.type == "MESH"
                               for m in o.data.materials)
                sh.light, sh.show_shadows, sh.show_cavity = "STUDIO", True, True
                sh.color_type = "TEXTURE" if textured else "MATERIAL"
                scene.display.render_aa = "8"
            else:
                scene.eevee.taa_render_samples = 16
            if scene.world is None:
                scene.world = bpy.data.worlds.new("r2r_world")
            scene.world.color = (0.82, 0.82, 0.84)
            r.filepath = str(path)
            t0 = time.perf_counter()
            bpy.ops.render.render(write_still=True)
            ms = (time.perf_counter() - t0) * 1000
        finally:
            for o, v in prior.items():
                if o.name in bpy.data.objects:
                    o.hide_render = v
            bpy.data.objects.remove(cam, do_unlink=True)
            bpy.data.objects.remove(sun, do_unlink=True)
        return {"path": str(path), "width_px": opts["width_px"], "height_px": opts["height_px"],
                "engine": opts["engine"], "view": opts["view"], "render_ms": round(ms, 1)}

    @staticmethod
    def _camera(scene, objs, view, aspect):
        pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
        hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 0.05)
        direction = {"iso": Vector((0.75, -1.0, 0.7)), "front": Vector((0.0, -1.0, 0.18)),
                     "top": Vector((0.0, -0.001, 1.0))}[view].normalized()
        cam_data = bpy.data.cameras.new("r2r_cam")
        cam_data.lens_unit = "FOV"
        cam_data.angle = math.radians(35)
        cam_data.clip_end = 1000
        fov = cam_data.angle if aspect >= 1 else 2 * math.atan(math.tan(cam_data.angle / 2) * aspect)
        dist = radius / math.sin(fov / 2) * 1.02
        cam = bpy.data.objects.new("r2r_cam", cam_data)
        scene.collection.objects.link(cam)
        cam.location = center + direction * dist
        cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam
        sun_data = bpy.data.lights.new("r2r_sun", type="SUN")
        sun_data.energy = 3.0
        sun = bpy.data.objects.new("r2r_sun", sun_data)
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        scene.collection.objects.link(sun)
        return cam, sun

    # ------------------------------------------------------------ dispatch

    def handle(self, raw: bytes, token: str) -> dict:
        try:
            req = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return {"id": None, "ok": False, "error": {"type": "bad_request", "message": f"invalid JSON: {exc}"}}
        rid = req.get("id") if isinstance(req, dict) else None
        if not isinstance(req, dict) or set(req) - {"id", "token", "cmd", "params"}:
            return {"id": rid, "ok": False, "error": {"type": "bad_request", "message": "request must be {id, token, cmd, params}"}}
        if token and not hmac.compare_digest(str(req.get("token", "")), token):
            return {"id": rid, "ok": False, "error": {"type": "auth", "message": "bad token"}}
        cmd, params = req.get("cmd"), req.get("params") or {}
        fn = self.commands.get(cmd) if isinstance(cmd, str) else None
        if fn is None:
            return {"id": rid, "ok": False, "error": {"type": "unknown_command",
                                                      "message": f"cmd must be one of {sorted(self.commands) + ['shutdown']}"}}
        if not isinstance(params, dict):
            return {"id": rid, "ok": False, "error": {"type": "validation", "message": "params must be an object"}}
        t0 = time.perf_counter()
        try:
            result = fn(params)
            return {"id": rid, "ok": True, "result": result, "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2)}
        except specs.ValidationError as exc:
            return {"id": rid, "ok": False, "error": {"type": "validation", "message": str(exc)}}
        except CommandError as exc:
            return {"id": rid, "ok": False, "error": {"type": exc.type, "message": str(exc)}}
        except Exception as exc:
            log("command failed:", cmd, "\n" + traceback.format_exc())
            return {"id": rid, "ok": False, "error": {"type": "internal", "message": f"{type(exc).__name__}: {exc}"}}


def _read_line(conn) -> bytes:
    buf = bytearray()
    while b"\n" not in buf:
        chunk = conn.recv(65536)
        if not chunk:
            break
        buf += chunk
        if len(buf) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
    return bytes(buf.split(b"\n", 1)[0])


def _parent_alive(pid: int | None) -> bool:
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(prog="worker.py")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--ready-file", default=None)
    ap.add_argument("--allowed-root", action="append", default=[])
    ap.add_argument("--parent-pid", type=int, default=None)
    ap.add_argument("--idle-exit-s", type=float, default=0, help="exit after this many idle seconds (0 = never)")
    args = ap.parse_args(argv)
    token = os.environ.get("R2R_WORKER_TOKEN", "")
    roots = [Path(r) for r in args.allowed_root] or [
        REPO / "backend" / "static" / "assets", REPO / "integrations" / "blender_mcp" / ".out", Path(tempfile.gettempdir())]
    worker = Worker(roots)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", args.port))
    sock.listen(16)
    sock.settimeout(1.0)
    port = sock.getsockname()[1]
    info = {"port": port, "pid": os.getpid(), "blender": bpy.app.version_string,
            "template_version": specs.TEMPLATE_VERSION, "allowed_roots": [str(r) for r in worker.allowed_roots]}
    if args.ready_file:
        tmp = Path(args.ready_file + ".tmp")
        tmp.write_text(json.dumps(info))
        os.replace(tmp, args.ready_file)
    print("R2R_WORKER_READY " + json.dumps(info), flush=True)

    last = time.monotonic()
    while True:
        try:
            conn, _ = sock.accept()
        except socket.timeout:
            if not _parent_alive(args.parent_pid):
                log("parent exited; shutting down")
                break
            if args.idle_exit_s and time.monotonic() - last > args.idle_exit_s:
                log("idle timeout; shutting down")
                break
            continue
        last = time.monotonic()
        with conn:
            conn.settimeout(30)
            try:
                raw = _read_line(conn)
                if raw.strip() and json.loads(raw).get("cmd") == "shutdown":
                    req = json.loads(raw)
                    if not token or hmac.compare_digest(str(req.get("token", "")), token):
                        conn.sendall(json.dumps({"id": req.get("id"), "ok": True, "result": {"shutdown": True}}).encode() + b"\n")
                        break
                resp = worker.handle(raw, token)
            except Exception as exc:
                resp = {"id": None, "ok": False, "error": {"type": "bad_request", "message": str(exc)}}
            try:
                conn.sendall(json.dumps(resp).encode("utf-8") + b"\n")
            except OSError:
                pass
    sock.close()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()

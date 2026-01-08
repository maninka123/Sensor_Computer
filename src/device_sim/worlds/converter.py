import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh


def parse_pose(pose_str):
    """Parse pose string 'x y z r p y' into a 4x4 transform."""
    if pose_str is None:
        return np.identity(4)
    parts = [float(p) for p in pose_str.split()]
    if len(parts) != 6:
        return np.identity(4)
    x, y, z, roll, pitch, yaw = parts
    rotation = trimesh.transformations.euler_matrix(roll, pitch, yaw)
    translation = trimesh.transformations.translation_matrix([x, y, z])
    return translation @ rotation


def parse_material_color(visual_element):
    """Return RGBA list (0-1) from diffuse and transparency; default grey."""
    material = visual_element.find("material") if visual_element is not None else None
    diffuse = material.find("diffuse") if material is not None else None
    transparency_tag = None
    if visual_element is not None:
        transparency_tag = visual_element.find("transparency")
    if transparency_tag is None and material is not None:
        transparency_tag = material.find("transparency")

    alpha = None
    if transparency_tag is not None and transparency_tag.text:
        try:
            tval = float(transparency_tag.text)
            alpha = max(0.0, min(1.0, 1.0 - tval))  # Gazebo transparency: 0 opaque, 1 fully transparent
        except ValueError:
            alpha = None

    color = [0.5, 0.5, 0.5, 1.0]
    if diffuse is not None and diffuse.text:
        try:
            comps = [float(c) for c in diffuse.text.split()]
            if len(comps) >= 3:
                if len(comps) == 3:
                    comps.append(1.0)
                color = comps[:4]
        except ValueError:
            pass

    if alpha is not None:
        color[3] = min(color[3], alpha)

    return color


def build_scene(world_path):
    """Load SDF world and build a trimesh.Scene."""
    tree = ET.parse(world_path)
    root = tree.getroot()
    world = root.find("world")

    # Support both <world> wrappers and standalone <model> SDFs
    if world is not None:
        models = world.findall("model")
        includes = world.findall("include")
    elif root.tag == "model":
        models = [root]
        includes = []
    else:
        models = root.findall("model")
        includes = root.findall("include")

    if not models and not includes:
        raise ValueError("No <world> or <model> element found in the SDF file.")

    scene = trimesh.Scene()
    world_dir = Path(world_path).resolve().parent

    def add_model(model_elem, parent_pose):
        model_name = model_elem.get("name", "model")
        model_pose = parent_pose @ parse_pose(model_elem.findtext("pose"))

        for link in model_elem.findall("link"):
            link_name = link.get("name", "link")
            link_pose = model_pose @ parse_pose(link.findtext("pose"))

            visuals = link.findall("visual")
            if not visuals:
                visuals = link.findall("collision")

            for idx, visual in enumerate(visuals):
                visual_name = visual.get("name", f"{link_name}_visual_{idx}")
                visual_pose = parse_pose(visual.findtext("pose"))

                geometry = visual.find("geometry")
                mesh = None
                if geometry is not None:
                    box = geometry.find("box")
                    cyl = geometry.find("cylinder")
                    if box is not None and box.find("size") is not None:
                        size = [float(s) for s in box.find("size").text.split()]
                        mesh = trimesh.creation.box(extents=size)
                    elif cyl is not None and cyl.find("radius") is not None and cyl.find("length") is not None:
                        radius = float(cyl.find("radius").text)
                        length = float(cyl.find("length").text)
                        mesh = trimesh.creation.cylinder(radius=radius, height=length, sections=32)

                if mesh is None:
                    continue

                rgba = parse_material_color(visual)
                mesh.visual.face_colors = [int(c * 255) for c in rgba]
                transform = link_pose @ visual_pose
                scene.add_geometry(mesh, geom_name=f"{model_name}_{visual_name}", transform=transform)

    # Direct models
    for model in models:
        add_model(model, np.identity(4))

    # Included models (only file-based URIs are handled here)
    for inc in includes:
        uri = inc.findtext("uri") or ""
        inc_pose = parse_pose(inc.findtext("pose"))

        # Resolve file paths (file:// or relative)
        path_text = uri
        if uri.startswith("file://"):
            path_text = uri[len("file://"):]
        inc_path = Path(path_text)
        if not inc_path.is_absolute():
            inc_path = world_dir / inc_path

        if not inc_path.exists():
            continue

        try:
            inc_tree = ET.parse(str(inc_path))
            inc_root = inc_tree.getroot()
            if inc_root.tag == "model":
                inc_models = [inc_root]
            else:
                inc_models = inc_root.findall("model")
            for m in inc_models:
                add_model(m, inc_pose)
        except Exception:
            # If an include fails, skip it rather than crash visualization/export.
            continue

    return scene

def view_obj(obj_path: str):
    """Open an OBJ file in the trimesh viewer."""
    mesh = trimesh.load(obj_path)
    if hasattr(mesh, "show"):
        mesh.show()


def sdf_to_obj(sdf_path: str, obj_path: str):
    """Convert an SDF file to an OBJ (with accompanying MTL)."""
    scene = build_scene(sdf_path)
    scene.export(obj_path)
    #view_obj(obj_path)

def main():
    # Set the default file to preview/export here.
    DEFAULT_WORLD = "Longwall_wth_3DUIDS.world"  # change to "longwall_simple.world" if desired
    try:
        scene = build_scene(DEFAULT_WORLD)
    except Exception as e:
        print(f"Failed to load scene: {e}")
        return

    try:
        print("Showing the scene (close the window to continue)...")
        scene.show()
    except ImportError:
        print('Viewer unavailable: install pyglet with `pip install "pyglet<2"` to enable visualization.')
    except Exception as e:
        print(f"Viewer error: {e}")

    try:
        print("Exporting to output.obj...")
        scene.export("Underground_world.obj")
        print("Exported output.obj (MTL written alongside if materials are present).")
    except Exception as e:
        print(f"Export failed: {e}")


if __name__ == "__main__":
    main()

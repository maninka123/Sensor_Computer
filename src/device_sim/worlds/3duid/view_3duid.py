import sys
from pathlib import Path

# Ensure converter.py in parent is importable
sys.path.append(str(Path(__file__).resolve().parents[1]))

import converter  # type: ignore


def main():
    # User-adjustable settings
    target = Path("3duid/patterns")  # SDF file or directory
    out = Path("3duid/patterns")     # where to place OBJ files

    if target.is_dir():
        sdf_paths = sorted(target.glob("*.sdf"))
    else:
        sdf_paths = [target]

    if not sdf_paths:
        print("No SDF files found.")
        return

    last_obj = None
    for sdf in sdf_paths:
        obj_out = out
        if Path(obj_out).is_dir():
            obj_out = Path(obj_out) / sdf.with_suffix(".obj").name
        last_obj = obj_out
        converter.sdf_to_obj(str(sdf), str(obj_out))
        print(f"Converted {sdf} -> {obj_out}")

    # Optionally view the last OBJ
    if last_obj:
        try:
            converter.view_obj(str(last_obj))
        except Exception:
            pass

if __name__ == "__main__":
    main()

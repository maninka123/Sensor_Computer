import random
import sys
from pathlib import Path

# Allow importing converter from project root
sys.path.append(str(Path(__file__).resolve().parents[1]))
import converter  # type: ignore

PANEL_W = 0.300  # meters
PANEL_H = 0.400
PANEL_T = 0.010
CELL = 0.050  # 50 mm grid
GRID_COLS = int(PANEL_W / CELL)
GRID_ROWS = int(PANEL_H / CELL)
ROD_H = 2.0
ROD_W = 0.02
BASE_W = 0.05
BASE_T = 0.02
BASE_COLOR = (0, 0, 0, 1)
ROD_COLOR = (0, 0, 0, 1)
PANEL_COLOR = (1, 1, 1, 1)
CELL_COLOR = (1, 0, 0, 1)


def color_tag(rgba):
    return f"{rgba[0]} {rgba[1]} {rgba[2]} {rgba[3]}"


def write_marker(idx: int, red_cells, out_path: Path):
    name = f"marker_{idx:03d}"
    panel_z = BASE_T + ROD_H + PANEL_H / 2
    panel_y = PANEL_T / 2
    parts = []

    # Base
    parts.append(f"""
      <link name="base">
        <visual name="visual">
          <geometry><box><size>{BASE_W} {BASE_W} {BASE_T}</size></box></geometry>
          <material><diffuse>{color_tag(BASE_COLOR)}</diffuse></material>
        </visual>
        <collision name="collision">
          <geometry><box><size>{BASE_W} {BASE_W} {BASE_T}</size></box></geometry>
        </collision>
        <pose>0 0 {BASE_T/2} 0 0 0</pose>
      </link>""")

    # Rod
    parts.append(f"""
      <link name="rod">
        <visual name="visual">
          <geometry><box><size>{ROD_W} {ROD_W} {ROD_H}</size></box></geometry>
          <material><diffuse>{color_tag(ROD_COLOR)}</diffuse></material>
        </visual>
        <collision name="collision">
          <geometry><box><size>{ROD_W} {ROD_W} {ROD_H}</size></box></geometry>
        </collision>
        <pose>0 0 {BASE_T + ROD_H/2} 0 0 0</pose>
      </link>""")

    # Panel
    parts.append(f"""
      <link name="panel">
        <visual name="visual">
          <geometry><box><size>{PANEL_W} {PANEL_T} {PANEL_H}</size></box></geometry>
          <material><diffuse>{color_tag(PANEL_COLOR)}</diffuse></material>
        </visual>
        <collision name="collision">
          <geometry><box><size>{PANEL_W} {PANEL_T} {PANEL_H}</size></box></geometry>
        </collision>
        <pose>0 {panel_y} {panel_z} 0 0 0</pose>
      </link>""")

    # Red cells (only interior grid; border left white)
    cell_t = PANEL_T * 1.05
    cell_y = panel_y + (cell_t - PANEL_T) / 2
    for r, c in red_cells:
        x = -PANEL_W / 2 + CELL / 2 + c * CELL
        z = panel_z - PANEL_H / 2 + CELL / 2 + r * CELL
        parts.append(f"""
      <link name="cell_{r}_{c}">
        <visual name="visual">
          <geometry><box><size>{CELL} {cell_t} {CELL}</size></box></geometry>
          <material><diffuse>{color_tag(CELL_COLOR)}</diffuse></material>
        </visual>
        <collision name="collision">
          <geometry><box><size>{CELL} {cell_t} {CELL}</size></box></geometry>
        </collision>
        <pose>{x} {cell_y} {z} 0 0 0</pose>
      </link>""")

    body = "\n".join(parts)
    sdf = f"""<?xml version=\"1.0\"?>
<sdf version=\"1.6\">
  <model name=\"{name}\">
    <static>true</static>
{body}
  </model>
</sdf>
"""
    out_path.write_text(sdf)


def random_cells(red_count, rng):
    interior_rows = range(1, GRID_ROWS - 1)
    interior_cols = range(1, GRID_COLS - 1)
    interior = [(r, c) for r in interior_rows for c in interior_cols]
    rng.shuffle(interior)
    return interior[:red_count]


def main():
    # User-adjustable settings
    count = 3            # how many markers to generate
    red_count = 8        # number of interior red cells per marker
    seed = 42            # random seed
    out_dir = Path("3duid/patterns")

    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, count + 1):
        cells = random_cells(red_count, rng)
        out_file = out_dir / f"marker_{i:03d}.sdf"
        write_marker(i, cells, out_file)
        obj_file = out_file.with_suffix(".obj")
        converter.sdf_to_obj(str(out_file), str(obj_file))
        print(f"wrote {out_file} and {obj_file} with {len(cells)} red cells")

if __name__ == "__main__":
    main()

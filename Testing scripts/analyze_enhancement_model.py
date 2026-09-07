#!/usr/bin/env python3
import argparse
import collections
import os
import shutil
import subprocess
import sys


def format_int(n: int) -> str:
    return f"{n:,}"


def shape_str(obj):
    try:
        return str(tuple(obj.shape))
    except Exception:
        return str(type(obj))


def to_shape_repr(output):
    if isinstance(output, (list, tuple)):
        return "[" + ", ".join(shape_str(x) for x in output) + "]"
    if isinstance(output, dict):
        return "{" + ", ".join(f"{k}:{shape_str(v)}" for k, v in output.items()) + "}"
    return shape_str(output)


def node_id(name: str) -> str:
    return "n_" + (name if name else "root").replace(".", "_")


def write_model_graph_dot(model, layer_shapes, dot_path):
    shape_map = {name: osh for name, _tname, osh in layer_shapes}
    lines = []
    lines.append("digraph FinetuneModel {")
    lines.append('  rankdir=LR;')
    lines.append('  graph [fontsize=10, fontname="Helvetica"];')
    lines.append('  node [shape=box, style="rounded,filled", fillcolor="#f7f7f7", color="#555555", fontsize=10, fontname="Helvetica"];')
    lines.append('  edge [color="#777777"];')

    # Nodes
    for name, module in model.named_modules():
        mtype = type(module).__name__
        params_local = sum(p.numel() for p in module.parameters(recurse=False))
        params_total = sum(p.numel() for p in module.parameters())
        disp_name = name if name else "model"
        label = f"{disp_name}\\n{mtype}\\nparams_local={params_local:,}\\nparams_total={params_total:,}"
        if name in shape_map:
            label += f"\\nout={shape_map[name]}"
        lines.append(f'  {node_id(name)} [label="{label}"];')

    # Edges
    for name, _module in model.named_modules():
        if name == "":
            continue
        parent = name.rsplit(".", 1)[0] if "." in name else ""
        lines.append(f"  {node_id(parent)} -> {node_id(name)};")

    lines.append("}")
    with open(dot_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze the image enhancement neural network architecture")
    parser.add_argument(
        "--model-dir",
        default="/home/pasindu/catkin_ws_actual/src/node_pc/scripts/Image_enchancemet",
        help="Directory containing model_1.py and weights/",
    )
    parser.add_argument(
        "--weights",
        default="Model_V1.pt",
        help="Weights filename under <model-dir>/weights, or absolute path",
    )
    parser.add_argument("--height", type=int, default=366, help="Dummy input height")
    parser.add_argument("--width", type=int, default=484, help="Dummy input width")
    parser.add_argument("--batch", type=int, default=1, help="Dummy batch size")
    parser.add_argument(
        "--device",
        default="cpu",
        choices=["cpu", "cuda", "auto"],
        help="Inference device for analysis",
    )
    parser.add_argument(
        "--graph-out",
        default="/home/pasindu/catkin_ws_actual/Testing scripts/NN_model/enhancement_model_graph",
        help="Output path prefix for graph files (without extension)",
    )
    parser.add_argument("--input-image", default="", help="Optional input image path for real inference output")
    parser.add_argument(
        "--output-image",
        default="/home/pasindu/catkin_ws_actual/Testing scripts/NN_model/enhancement_model_output.png",
        help="Path to save enhanced output image when --input-image is provided",
    )
    args = parser.parse_args()

    model_dir = os.path.abspath(args.model_dir)
    if not os.path.isdir(model_dir):
        print(f"ERROR: model directory not found: {model_dir}")
        sys.exit(1)

    if model_dir not in sys.path:
        sys.path.append(model_dir)

    try:
        import torch
    except Exception as exc:
        print(f"ERROR: failed to import torch: {exc}")
        sys.exit(1)

    try:
        from model_1 import Finetunemodel
    except Exception as exc:
        print(f"ERROR: failed to import Finetunemodel from model_1.py: {exc}")
        sys.exit(1)

    weights_path = args.weights
    if not os.path.isabs(weights_path):
        weights_path = os.path.join(model_dir, "weights", weights_path)
    weights_path = os.path.abspath(weights_path)

    if not os.path.exists(weights_path):
        print(f"ERROR: weights file not found: {weights_path}")
        sys.exit(1)

    if args.device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = args.device

    print("=" * 90)
    print("Enhancement Model Analysis")
    print("=" * 90)
    print(f"model_dir   : {model_dir}")
    print(f"weights     : {weights_path}")
    print(f"device      : {device}")
    print(f"input_shape : ({args.batch}, 3, {args.height}, {args.width})")

    model = Finetunemodel(weights_path).to(device)
    model.eval()

    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    print("\n[Architecture]")
    print(model)

    print("\n[Parameter Summary]")
    print(f"total_params     : {format_int(total_params)}")
    print(f"trainable_params : {format_int(trainable_params)}")
    print(f"frozen_params    : {format_int(total_params - trainable_params)}")
    print("note             : graph shows both params_local and params_total")

    by_type = collections.Counter()
    by_type_params = collections.Counter()
    for _name, module in model.named_modules():
        if len(list(module.children())) == 0:
            tname = type(module).__name__
            by_type[tname] += 1
            by_type_params[tname] += sum(p.numel() for p in module.parameters(recurse=False))

    print("\n[Leaf Layer Breakdown]")
    print(f"{'LayerType':<24} {'Count':>8} {'Params':>14}")
    print("-" * 50)
    for tname in sorted(by_type.keys()):
        print(f"{tname:<24} {by_type[tname]:>8} {format_int(by_type_params[tname]):>14}")

    # Forward hook summary
    layer_shapes = []
    hooks = []

    def make_hook(name):
        def _hook(_module, _inputs, output):
            layer_shapes.append((name, type(_module).__name__, to_shape_repr(output)))

        return _hook

    for name, module in model.named_modules():
        if len(list(module.children())) == 0:
            hooks.append(module.register_forward_hook(make_hook(name)))

    x = torch.rand(args.batch, 3, args.height, args.width, device=device)
    with torch.no_grad():
        out = model(x)

    for h in hooks:
        h.remove()

    print("\n[Model Output]")
    print(f"output_type : {type(out).__name__}")
    print(f"output_shape: {to_shape_repr(out)}")

    print("\n[Forward Shape Trace (leaf modules)]")
    print(f"{'ModuleName':<40} {'Type':<20} Output")
    print("-" * 100)
    for name, tname, osh in layer_shapes:
        print(f"{name:<40} {tname:<20} {osh}")

    graph_out = os.path.abspath(args.graph_out)
    graph_dir = os.path.dirname(graph_out)
    if graph_dir and not os.path.isdir(graph_dir):
        os.makedirs(graph_dir, exist_ok=True)
    dot_path = graph_out + ".dot"
    write_model_graph_dot(model, layer_shapes, dot_path)
    print("\n[Graph Output]")
    print(f"dot : {dot_path}")

    dot_bin = shutil.which("dot")
    if dot_bin:
        png_path = graph_out + ".png"
        svg_path = graph_out + ".svg"
        try:
            subprocess.run([dot_bin, "-Tpng", dot_path, "-o", png_path], check=True)
            subprocess.run([dot_bin, "-Tsvg", dot_path, "-o", svg_path], check=True)
            print(f"png : {png_path}")
            print(f"svg : {svg_path}")
        except Exception as exc:
            print(f"WARNING: Graphviz render failed: {exc}")
    else:
        print("WARNING: Graphviz 'dot' not found. Install graphviz to render PNG/SVG from the DOT file.")

    if args.input_image:
        try:
            import numpy as np
            from PIL import Image
        except Exception as exc:
            print(f"WARNING: Cannot export output image, missing dependency: {exc}")
        else:
            in_path = os.path.abspath(args.input_image)
            out_path = os.path.abspath(args.output_image)
            if os.path.exists(in_path):
                img = Image.open(in_path).convert("RGB")
                arr = np.asarray(img, dtype=np.float32) / 255.0
                x_img = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device)
                with torch.no_grad():
                    out_img = model(x_img)
                # Finetunemodel returns (i, r); runtime enhancer uses second output.
                y = out_img[1] if isinstance(out_img, (tuple, list)) else out_img
                y = y[0].detach().cpu().clamp(0, 1).permute(1, 2, 0).numpy()
                y8 = (y * 255.0).astype(np.uint8)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                Image.fromarray(y8).save(out_path)
                print("\n[Inference Output]")
                print(f"input  : {in_path}")
                print(f"output : {out_path}")
            else:
                print(f"WARNING: --input-image not found: {in_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()

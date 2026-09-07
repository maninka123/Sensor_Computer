# Image Enhancement Model Documentation

## 1. Purpose
This model enhances camera images before LiDAR-color fusion in your ROS pipeline.

It is used by:
- `src/node_pc/scripts/image_enhancer.py`
- `src/node_pc/scripts/Image_enchancemet/lidar_image_model.py`

The enhanced image topic is:
- `/camera/image_enhanced`

## 2. Model Files and Runtime Path

Core model definition:
- `src/node_pc/scripts/Image_enchancemet/model_1.py`

Runtime wrapper used in ROS node:
- `src/node_pc/scripts/Image_enchancemet/lidar_image_model.py`

Weights file used by runtime:
- `src/node_pc/scripts/Image_enchancemet/weights/Model_V1.pt`

Important runtime behavior:
- `Finetunemodel.forward()` returns a tuple: `(i, r)`
- Runtime code always uses `r` as final enhanced output (`output[1]`)

## 3. High-Level Architecture

The runtime model class is `Finetunemodel`, which contains only `EnhanceNetwork`.

`EnhanceNetwork` structure:
1. `in_conv`: `Conv2d(3->3, k=3, s=1, p=1)` + `ReLU`
2. Residual block stack (`layers=1` in current runtime):
   - `Conv2d(3->3, k=3, s=1, p=1)` + `BatchNorm2d(3)` + `ReLU`
   - Residual update: `fea = fea + block(fea)`
3. `out_conv`: `Conv2d(3->3, k=3, s=1, p=1)` + `Sigmoid`
4. Illumination-like output:
   - `i = clamp(fea + input, 1e-4, 1.0)`

Then `Finetunemodel` computes:
- `r = clamp(input / i, 0, 1)`
- returns `(i, r)`

### Why output size stays the same
All convolutions are stride 1 with padding 1 and no pooling/upsampling.
So input and outputs remain `(B, 3, H, W)`.

## 4. Mathematical Interpretation

Let input image be `x` in `[0,1]`.

The network predicts an illumination correction map `i`:
- `i = f_theta(x)` (implemented as conv + residual + sigmoid + skip with input)

Enhanced result is computed as:
- `r = x / i`
- then clamped to `[0,1]`

Interpretation:
- Dark regions often get smaller `i`, causing larger `x/i` (brightening)
- Brighter regions get less amplification

This is closer to a learned illumination normalization / retinex-style formulation than generic denoising.

## 5. Output Selection (Important)

There is no dynamic branch selection.

`Finetunemodel.forward()` always returns two tensors in fixed order:
1. `i`
2. `r`

Runtime enhancer always publishes the second one:
- `lidar_image_model.py` picks `output[1]`

So the deployed enhancement output is always `r`.

## 6. Parameter Count and Why It Looks Small

This model is intentionally lightweight (~258 parameters in your graph summary), because:
- all channels are 3 in `EnhanceNetwork`
- only one residual block in runtime (`layers=1`)
- tiny conv stack for fast ROS inference

In the graph:
- `params_local` = parameters directly owned by that module
- `params_total` = parameters in that module subtree

Container modules (`Sequential`, `ModuleList`) can have `params_local=0` but non-zero `params_total`.

## 7. ROS Integration Flow

1. `image_enhancer.py` subscribes to `/camera/image_raw`
2. If enhancement enabled (`/image_enhancement == True`), it calls `lidar_image_model.process_image()`
3. `process_image()` runs model and returns enhanced frame (`r`)
4. Publishes `/camera/image_enhanced`
5. `pointcloud_colorize_node` uses raw or enhanced image based on `/image_enhancement`

## 8. What the Graph Visualization Represents

The generated model graph is module hierarchy, not multiple final output branches.

So when you see many arrows/paths, those are parent-child module relations and internal layer flow, not "choose one branch" logic.

Final runtime output remains deterministic:
- always tuple `(i, r)`
- runtime uses `r`

## 9. How to Analyze and Export Graph

Script:
- `Testing scripts/analyze_enhancement_model.py`

Default outputs to:
- `Testing scripts/NN_model/enhancement_model_graph.dot`
- `Testing scripts/NN_model/enhancement_model_graph.png` (if Graphviz installed)
- `Testing scripts/NN_model/enhancement_model_graph.svg` (if Graphviz installed)

Run:
```bash
python3 "Testing scripts/analyze_enhancement_model.py"
```

Generate example enhanced image from a real input:
```bash
python3 "Testing scripts/analyze_enhancement_model.py" \
  --input-image /path/to/input.png
```

Output image path (default):
- `Testing scripts/NN_model/enhancement_model_output.png`

## 10. Limitations and Practical Notes

- Very small model: fast, but limited expressiveness for challenging scenes.
- Uses global learned behavior via convs, not explicit scene semantics.
- No explicit exposure metadata or noise model in inference path.
- Quality can vary under extreme lighting, glare, or motion blur.
- If needed, stronger enhancement requires retraining or a larger model variant.

## 11. Summary

Your deployed enhancer is a compact convolutional illumination-correction network.
It predicts an illumination map `i` and produces enhanced image `r = input / i`.
ROS runtime always publishes `r` (second returned output).

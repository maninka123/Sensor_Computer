#!/usr/bin/env python3
import os
from typing import Tuple

import cv2
import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from model_1 import Finetunemodel

SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))

# Edit these variables directly
INPUT_IMAGE = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw.png")
OUTPUT_IMAGE = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_illumination.png")
OUTPUT_GRAY = None  # Example: os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_illumination_gray.png")
OUTPUT_HEATMAP = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_illumination_heatmap.png")
OUTPUT_ENHANCED = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_enhanced.png")
OUTPUT_IMPROVEMENT_HEATMAP = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_improvement_heatmap.png")
OUTPUT_IMPROVEMENT_OVERLAY = os.path.join(SCRIPT_DIR, "sample image", "20260219_171130_raw_improvement_overlay.png")
HEATMAP_STYLE = "turbo"  # "turbo" or "jet"
OVERLAY_ALPHA = 0.55  # 0.0 -> only original, 1.0 -> only heatmap
ROTATE_CLOCKWISE_90 = True
WEIGHTS_PATH = os.path.join(SCRIPT_DIR, "weights", "Model_V3.pt")


def tensor_to_uint8_image(tensor: torch.Tensor) -> np.ndarray:
    image_numpy = tensor[0].detach().cpu().float().numpy()
    image_numpy = np.transpose(image_numpy, (1, 2, 0))
    return np.clip(image_numpy * 255.0, 0, 255.0).astype(np.uint8)


def save_gray_from_rgb(rgb_image: np.ndarray, path: str) -> None:
    gray = np.mean(rgb_image.astype(np.float32), axis=2)
    gray = np.clip(gray, 0, 255).astype(np.uint8)
    Image.fromarray(gray, mode="L").save(path)


def build_heatmap_from_rgb(rgb_image: np.ndarray, style: str = "turbo") -> Tuple[np.ndarray, float, float]:
    gray = np.mean(rgb_image.astype(np.float32), axis=2)
    min_v = float(gray.min())
    max_v = float(gray.max())
    if max_v - min_v < 1e-6:
        norm = np.zeros_like(gray, dtype=np.uint8)
    else:
        norm = ((gray - min_v) / (max_v - min_v) * 255.0).astype(np.uint8)

    colormap = cv2.COLORMAP_TURBO if style.lower() == "turbo" else cv2.COLORMAP_JET
    heatmap_bgr = cv2.applyColorMap(norm, colormap)
    heatmap_rgb = cv2.cvtColor(heatmap_bgr, cv2.COLOR_BGR2RGB)
    return heatmap_rgb, min_v, max_v


def make_improvement_heatmap(original_rgb: np.ndarray, enhanced_rgb: np.ndarray, style: str = "turbo") -> Tuple[np.ndarray, float]:
    original_gray = np.mean(original_rgb.astype(np.float32), axis=2)
    enhanced_gray = np.mean(enhanced_rgb.astype(np.float32), axis=2)

    # Positive brightness increase from input to enhanced output.
    improvement = np.maximum(enhanced_gray - original_gray, 0.0)
    p99 = float(np.percentile(improvement, 99.0))
    if p99 < 1e-6:
        norm = np.zeros_like(improvement, dtype=np.uint8)
    else:
        norm = np.clip((improvement / p99) * 255.0, 0.0, 255.0).astype(np.uint8)

    colormap = cv2.COLORMAP_TURBO if style.lower() == "turbo" else cv2.COLORMAP_JET
    heatmap_bgr = cv2.applyColorMap(norm, colormap)
    return cv2.cvtColor(heatmap_bgr, cv2.COLOR_BGR2RGB), p99


def save_overlay(base_rgb: np.ndarray, heatmap_rgb: np.ndarray, path: str, alpha: float = 0.55) -> None:
    alpha = float(np.clip(alpha, 0.0, 1.0))
    overlay = cv2.addWeighted(base_rgb, 1.0 - alpha, heatmap_rgb, alpha, 0.0)
    Image.fromarray(overlay).save(path)


def add_heatmap_legend(
    image_rgb: np.ndarray,
    style: str = "turbo",
    low_text: str = "Low",
    mid_text: str = "Medium",
    high_text: str = "High",
) -> np.ndarray:
    h, w, _ = image_rgb.shape
    pad = max(6, h // 80)
    bar_h = max(10, h // 45)
    text_h = max(20, h // 16)
    font_scale = 0.4
    thickness = 1

    grad = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    grad = np.repeat(grad, bar_h, axis=0)
    colormap = cv2.COLORMAP_TURBO if style.lower() == "turbo" else cv2.COLORMAP_JET
    grad_bgr = cv2.applyColorMap(grad, colormap)
    grad_rgb = cv2.cvtColor(grad_bgr, cv2.COLOR_BGR2RGB)
    canvas = np.full((h + pad + bar_h + text_h + pad, w, 3), 255, dtype=np.uint8)
    canvas[:h, :, :] = image_rgb
    y0 = h + pad
    canvas[y0:y0 + bar_h, :, :] = grad_rgb

    cv2.rectangle(canvas, (0, y0), (w - 1, y0 + bar_h), (0, 0, 0), 1)

    y_text = y0 + bar_h + max(12, text_h - 7)
    cv2.putText(canvas, low_text, (2, y_text), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    mid_size = cv2.getTextSize(mid_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0]
    mid_x = max(2, (w - mid_size[0]) // 2)
    cv2.putText(canvas, mid_text, (mid_x, y_text), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    high_size = cv2.getTextSize(high_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)[0]
    high_x = max(2, w - high_size[0] - 2)
    cv2.putText(canvas, high_text, (high_x, y_text), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    return canvas


def main() -> None:
    input_path = INPUT_IMAGE
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input image not found: {input_path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = Finetunemodel(WEIGHTS_PATH).to(device)
    model.eval()

    image = Image.open(input_path).convert("RGB")
    if ROTATE_CLOCKWISE_90:
        image = image.transpose(Image.ROTATE_270)
    original_rgb = np.array(image, dtype=np.uint8)
    input_tensor = transforms.ToTensor()(image).unsqueeze(0).to(device)

    with torch.no_grad():
        illumination_map, enhanced_map = model(input_tensor)

    illumination_rgb = tensor_to_uint8_image(illumination_map)
    enhanced_rgb = tensor_to_uint8_image(enhanced_map)

    output_path = OUTPUT_IMAGE if OUTPUT_IMAGE else (os.path.splitext(input_path)[0] + "_illumination.png")
    Image.fromarray(illumination_rgb).save(output_path)
    print(f"Saved RGB illumination map: {output_path}")

    if OUTPUT_ENHANCED:
        Image.fromarray(enhanced_rgb).save(OUTPUT_ENHANCED)
        print(f"Saved enhanced image: {OUTPUT_ENHANCED}")

    if OUTPUT_GRAY:
        save_gray_from_rgb(illumination_rgb, OUTPUT_GRAY)
        print(f"Saved grayscale illumination map: {OUTPUT_GRAY}")

    if OUTPUT_HEATMAP:
        heatmap_img, illum_min, illum_max = build_heatmap_from_rgb(illumination_rgb, HEATMAP_STYLE)
        heatmap_with_legend = add_heatmap_legend(
            heatmap_img,
            HEATMAP_STYLE,
            low_text="Dark",
            mid_text="Neutral",
            high_text="Bright",
        )
        Image.fromarray(heatmap_with_legend).save(OUTPUT_HEATMAP)
        print(f"Saved illumination heatmap: {OUTPUT_HEATMAP}")

    if OUTPUT_IMPROVEMENT_HEATMAP or OUTPUT_IMPROVEMENT_OVERLAY:
        improvement_heatmap, p99 = make_improvement_heatmap(original_rgb, enhanced_rgb, HEATMAP_STYLE)

        if OUTPUT_IMPROVEMENT_HEATMAP:
            improvement_with_legend = add_heatmap_legend(
                improvement_heatmap,
                HEATMAP_STYLE,
                low_text="Low",
                mid_text="Medium",
                high_text="High",
            )
            Image.fromarray(improvement_with_legend).save(OUTPUT_IMPROVEMENT_HEATMAP)
            print(f"Saved improvement heatmap: {OUTPUT_IMPROVEMENT_HEATMAP}")

        if OUTPUT_IMPROVEMENT_OVERLAY:
            overlay = cv2.addWeighted(original_rgb, 1.0 - float(np.clip(OVERLAY_ALPHA, 0.0, 1.0)), improvement_heatmap, float(np.clip(OVERLAY_ALPHA, 0.0, 1.0)), 0.0)
            overlay_with_legend = add_heatmap_legend(
                overlay,
                HEATMAP_STYLE,
                low_text="Low",
                mid_text="Medium",
                high_text="High",
            )
            Image.fromarray(overlay_with_legend).save(OUTPUT_IMPROVEMENT_OVERLAY)
            print(f"Saved improvement overlay: {OUTPUT_IMPROVEMENT_OVERLAY}")


if __name__ == "__main__":
    main()

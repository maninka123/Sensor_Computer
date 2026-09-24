"""Small, bounded colour correction for warm dome reflections.

This operates on BGR8 pixels only. It preserves image dimensions and headers,
and cannot restore detail hidden by saturated reflections.
"""

import cv2


def correct_bgr(image):
    blue, green, red = cv2.split(image)
    blue = cv2.add(blue, 2)
    red = cv2.subtract(red, 2)

    warm = cv2.min(
        cv2.subtract(red, cv2.add(green, 6)),
        cv2.subtract(green, cv2.add(blue, 2)),
    )
    warm = cv2.min(warm, 24)
    brightness = cv2.min(
        cv2.subtract(cv2.max(cv2.max(blue, green), red), 100), 80
    )
    shift = cv2.multiply(warm, brightness, scale=0.3 / 80.0)
    return cv2.merge((cv2.add(blue, shift), green, cv2.subtract(red, shift)))

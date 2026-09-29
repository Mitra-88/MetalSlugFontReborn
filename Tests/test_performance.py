
import time

from image_generation import generate_image, get_font_paths


def test_typical_text_renders_quickly():
    font_paths = get_font_paths(1, "Blue")
    start = time.perf_counter()
    generate_image("Hello World!", "preview", font_paths, None, return_image=True)
    assert time.perf_counter() - start < 1.0


def test_long_text_renders_quickly():
    font_paths = get_font_paths(1, "Blue")
    text = "METAL SLUG IS PEAK! " * 100
    start = time.perf_counter()
    generate_image(text, "preview", font_paths, None, return_image=True)
    assert time.perf_counter() - start < 3.0

# Standard library imports
import os
from pathlib import Path
from typing import Optional, Tuple

# Third-party imports
import cv2
import numpy as np
from skimage import filters
import matplotlib.pyplot as plt


MINIMUM_THICKNESS_PIXELS = 10
PIXELS_TO_METERS = 1e-6
FILM_SOBEL_THRESHOLD = 0.05
IMAGE_CROP_LEFT = 2

output_dir = Path(__file__).parent.parent / "devices" / "Film_Images"


def detect_film_rim(edge_x: np.ndarray, edge_y: np.ndarray, keep_top_only: bool) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect top/bottom rim coordinates from edge pixels.

    Find the outermost edge pixels for each x-coordinate, which correspond to the film rim. This is done by sorting the edge pixels by x-coordinate and then pairing the first and last y-values for each unique x-value.
    """
    x_current = edge_x[0]
    x_range = max(edge_x) - min(edge_x)

    y_rim = np.zeros(x_range * 5)
    x_rim = np.zeros(x_range * 5)

    sorted_indices = np.lexsort((edge_y, edge_x))
    edge_x_sorted = edge_x[sorted_indices]
    edge_y_sorted = edge_y[sorted_indices]

    rim_index = 0
    for i in range(len(edge_x_sorted)):
        if x_current != edge_x_sorted[i]:
            rim_index += 2

            if not keep_top_only:
                x_rim[rim_index - 1] = x_current
                y_rim[rim_index - 1] = edge_y_sorted[i]

            x_rim[rim_index] = edge_x_sorted[i]
            y_rim[rim_index] = edge_y_sorted[i - 1]

        x_current = edge_x_sorted[i]

    return x_rim[:2 * rim_index], y_rim[:2 * rim_index]


def filter_film_rim_by_x_range(rim_x: np.ndarray, rim_y: np.ndarray,
                               x_min: float, x_max: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Keep only rim points inside the x-range used for thickness extraction.
    """
    mask_right = x_min < rim_x
    rim_x_filtered = rim_x[mask_right]
    rim_y_filtered = rim_y[mask_right]

    mask_left = rim_x_filtered < x_max
    return rim_x_filtered[mask_left], rim_y_filtered[mask_left]


def calculate_film_thickness_from_rim(rim_x: np.ndarray, rim_y: np.ndarray, plate_height: float) -> list:
    """
    Calculate thickness values in meters from paired rim coordinates.
    """
    thicknesses = []

    sorted_indices = np.lexsort((rim_y, rim_x))
    rim_x_sorted = rim_x[sorted_indices]
    rim_y_sorted = rim_y[sorted_indices]

    for i in range(0, len(rim_x_sorted) - 1, 1):
        bottom = plate_height  # rim_y_sorted[i]
        top = rim_y_sorted[i]
        thickness = np.abs(top - bottom)

        if thickness >= MINIMUM_THICKNESS_PIXELS:
            thicknesses.append(thickness)

    return thicknesses


def determine_film_height(image_path, plate_height, output_dir) -> float:
    """
    Determine mean film height in millimeters for one frame.
    """
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Image not found at path: {image_path}")
    image = image[::-1, :]

    edge_map = cv2.Canny(image, 50, 150)
    edge_y, edge_x = np.where(edge_map != 0)
    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    rim_x, rim_y = detect_film_rim(edge_x, edge_y, keep_top_only=True)
    _, image_width = image.shape
    min_x = (image_width // 2)
    IMAGE_CROP_RIGHT = image_width - 2
    rim_x, rim_y = filter_film_rim_by_x_range(
        rim_x, rim_y, min_x, IMAGE_CROP_RIGHT)

    thicknesses = calculate_film_thickness_from_rim(
        rim_x, rim_y, plate_height)
    if not thicknesses:
        raise ValueError("No valid film-height thickness values found")
    thickness = float(np.mean(thicknesses))

    plt.figure()
    plt.imshow(image, cmap='gray', origin='lower')
    plt.scatter(rim_x, rim_y, s=1, color='red')
    plt.title(f"Film Height: {thickness:.2f} px")
    plt.savefig(output_dir / "film_height.png")
    # plt.show()

    return thickness


def determine_plate_height(background_path, output_dir) -> float:
    """
    Determine the plate height in pixels.
    """
    background = cv2.imread(str(background_path), cv2.IMREAD_GRAYSCALE)
    if background is None:
        raise RuntimeError(
            f"Failed to read captured image from: {background_path}")
    background = background[::-1, :]

    edge_map = cv2.Canny(background, 50, 150)
    edge_y, edge_x = np.where(edge_map != 0)

    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    top_x, top_y = detect_film_rim(edge_x, edge_y, keep_top_only=True)
    _, image_width = background.shape
    min_x = (image_width // 2)
    IMAGE_CROP_RIGHT = image_width - 2
    top_x, top_y = filter_film_rim_by_x_range(
        top_x, top_y, min_x, IMAGE_CROP_RIGHT)

    plate_height = float(np.mean(top_y))
    if not plate_height:
        raise ValueError("No valid plate height values found")

    plt.figure()
    plt.imshow(background, cmap='gray', origin='lower')
    plt.scatter(top_x, top_y, s=1, color='red')
    plt.title(f"Plate Height: {plate_height:.1f} px")
    plt.savefig(output_dir / "background_plate_height.png")
    # plt.show()

    return plate_height


if __name__ == "__main__":
    output_dir = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera")

    background_path = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera\capture_20260622_152241.png")

    plate_height = determine_plate_height(background_path, output_dir)
    print(f"Determined plate height: {plate_height:.1f} px")

    image_path = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera\capture_20260622_152426.png")

    film_height_px = determine_film_height(
        image_path, plate_height, output_dir)
    print(f"Determined film height: {film_height_px:.2f} px")

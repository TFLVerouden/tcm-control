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



def detect_film_rim(edge_x: np.ndarray, edge_y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
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
            x_rim[rim_index - 1] = x_current
            x_rim[rim_index] = edge_x_sorted[i]
            y_rim[rim_index - 1] = edge_y_sorted[i]
            y_rim[rim_index] = edge_y_sorted[i - 1]

        x_current = edge_x_sorted[i]

    return x_rim[:2 * rim_index], y_rim[:2 * rim_index]



def filter_film_rim_by_x_range(rim_x: np.ndarray, rim_y: np.ndarray,
                               x_min: float, x_max: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Keep only rim points inside the x-range used for thickness extraction.
    """
    mask_left = x_min < rim_x
    rim_x_filtered = rim_x[mask_left]
    rim_y_filtered = rim_y[mask_left]

    mask_right = rim_x_filtered < x_max
    return rim_x_filtered[mask_right], rim_y_filtered[mask_right]



def calculate_film_thickness_from_rim(rim_x: np.ndarray, rim_y: np.ndarray) -> list:
    """
    Calculate thickness values in meters from paired rim coordinates.
    """
    thicknesses = []

    sorted_indices = np.lexsort((rim_y, rim_x))
    rim_x_sorted = rim_x[sorted_indices]
    rim_y_sorted = rim_y[sorted_indices]

    for i in range(0, len(rim_x_sorted) - 1, 2):
        bottom = rim_y_sorted[i]
        top = rim_y_sorted[i + 1]
        thickness = np.abs(top - bottom)

        if thickness >= MINIMUM_THICKNESS_PIXELS:
            thicknesses.append(thickness * PIXELS_TO_METERS)

    return thicknesses



def determine_film_height(image) -> float:
    """
    Determine mean film height in millimeters for one frame.
    """

    # edge_map = filters.sobel(image)
    edge_map = cv2.Canny(image, 50, 80)
    # binary_edges = edge_map > FILM_SOBEL_THRESHOLD
    edge_y, edge_x = np.where(edge_map != 0)

    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    rim_x, rim_y = detect_film_rim(edge_x, edge_y)
    _, image_width = image.shape
    max_x = (image_width // 2) 
    rim_x, rim_y = filter_film_rim_by_x_range(rim_x, rim_y, IMAGE_CROP_LEFT, max_x)

    thicknesses = calculate_film_thickness_from_rim(rim_x, rim_y)
    if not thicknesses:
        raise ValueError("No valid film-height thickness values found")

    return rim_x, rim_y, float(np.mean(thicknesses) * 1000.0)



if __name__ == "__main__":
   
    image_path = Path(r"F:\singleimage.tif")
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    
    image = image[::-1, :]

    rim_x, rim_y, film_height = determine_film_height(image)

    plt.figure()
    plt.imshow(image, cmap='gray', origin='lower')
    plt.scatter(rim_x, rim_y, s=1, color='red')
    plt.title(f"Film Height: {film_height:.4f} mm")
    plt.show()
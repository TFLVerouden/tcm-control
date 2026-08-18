"""Film height measurement from camera images."""

from pathlib import Path
from typing import Tuple

import cv2
import numpy as np
import matplotlib.pyplot as plt

# Constants for film height detection
MINIMUM_THICKNESS_PIXELS = 10
IMAGE_CROP_LEFT = 2


def detect_film_rim(
    edge_x: np.ndarray,
    edge_y: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Detect top/bottom rim coordinates from edge pixels.

    Edge detection usually gives multiple edge pixels for each x-coordinate. 
    Find the outermost edge pixels for each x-coordinate, which correspond to
    the film rim. This is done by sorting the edge pixels by x-coordinate and
    then finding the minimum and maximum y-values for each unique x-value.

    Args:
        edge_x: X-coordinates of detected edge pixels.
        edge_y: Y-coordinates of detected edge pixels.

    Returns:
        Tuple of (x_coordinates, y_coordinates) for the detected film rim.
    """
    x_current = edge_x[0]
    x_range = max(edge_x) - min(edge_x)

    # Pre-allocate arrays with buffer space for rim coordinates
    y_rim = np.zeros(x_range * 5)
    x_rim = np.zeros(x_range * 5)

    # Sort edge pixels by x-coordinate (primary) and y-coordinate (secondary)
    sorted_indices = np.lexsort((edge_y, edge_x))
    edge_x_sorted = edge_x[sorted_indices]
    edge_y_sorted = edge_y[sorted_indices]

    # Extract rim coordinates by finding extreme y-values for each x-value
    rim_index = 0
    for i in range(len(edge_x_sorted)):
        if x_current != edge_x_sorted[i]:
            # New x-coordinate found: store the rim point(s)
            rim_index += 2

            # Store top rim point (current maximum y)
            x_rim[rim_index] = edge_x_sorted[i]
            y_rim[rim_index] = edge_y_sorted[i - 1]

        x_current = edge_x_sorted[i]

    # Return only the valid portion of the arrays
    return x_rim[:2 * rim_index], y_rim[:2 * rim_index]


def filter_film_rim_by_x_range(
    rim_x: np.ndarray,
    rim_y: np.ndarray,
    x_min: float,
    x_max: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Filter rim coordinates to a specific x-range.

    Only keep the rim coordinates between x_min and x_max. This way, we keep 
    the rim points within the constant height range, not close to the 
    contact line. 

    Args:
        rim_x: X-coordinates of rim points.
        rim_y: Y-coordinates of rim points.
        x_min: Minimum x-coordinate to keep.
        x_max: Maximum x-coordinate to keep.

    Returns:
        Tuple of (filtered_x, filtered_y) coordinates within the specified range.
    """
    mask_right = x_min < rim_x
    rim_x_filtered = rim_x[mask_right]
    rim_y_filtered = rim_y[mask_right]

    mask_left = rim_x_filtered < x_max
    return rim_x_filtered[mask_left], rim_y_filtered[mask_left]


def determine_film_height(
    image_path: Path,
    plate_height: float,
    output_dir: Path,
) -> float:
    """Determine mean film height in pixels.

    Args:
        image_path: Path to the camera image file.
        plate_height: Plate height in pixels (determined from the background image).
        output_dir: Directory to save visualization.

    Returns:
        Film thickness in pixels (mean rim height minus plate height).
    """
    # Load and flip image (image coordinate system vs. plot coordinate system)
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"Image not found at path: {image_path}")
    image = image[::-1, :]  # Flip vertically for correct coordinate system

    # Detect edges using Canny edge detection
    edge_map = cv2.Canny(image, 50, 150)
    edge_y, edge_x = np.where(edge_map != 0)
    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    # Detect film rim from edges
    rim_x, rim_y = detect_film_rim(edge_x, edge_y)

    # Filter to right half of image
    _, image_width = image.shape
    min_x = image_width // 2
    max_x = image_width - 2  # Crop right edge
    rim_x, rim_y = filter_film_rim_by_x_range(rim_x, rim_y, min_x, max_x)

    # Calculate film thickness
    thickness = float(np.mean(rim_y) - plate_height)
    print(min_x, max_x)
    # Save visualization
    plt.figure()
    plt.imshow(image, cmap='gray', origin='lower')
    plt.scatter(rim_x, rim_y, s=1, color='blue')
    plt.axhline(y=plate_height, xmin=float(min_x)/image_width, xmax=float(
                max_x), color='green')
    plt.title(f"Film Height: {thickness:.2f} px")
    plt.savefig(output_dir / "film_height.png")
    plt.close()
    return thickness


def determine_plate_height(
    background_path: Path,
    output_dir: Path,
) -> float:
    """Determine the plate height in pixels from a background image.

    Analyzes a background image (typically captured without the film layer)
    to determine the baseline plate height position.

    Args:
        background_path: Path to the background image file.
        output_dir: Directory to save diagnostic visualization.

    Returns:
        Plate height in pixels (mean y-coordinate of detected rim).
    """
    # Load and flip image (image coordinate system vs. plot coordinate system)
    background = cv2.imread(str(background_path), cv2.IMREAD_GRAYSCALE)
    if background is None:
        raise RuntimeError(
            f"Failed to read captured image from: {background_path}"
        )
    # Flip vertically for correct coordinate system
    background = background[::-1, :]

    # Detect edges using Canny edge detection
    edge_map = cv2.Canny(background, 50, 150)
    edge_y, edge_x = np.where(edge_map != 0)

    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    # Detect rim from edges
    top_x, top_y = detect_film_rim(edge_x, edge_y)

    # Filter to right half of image (avoid boundary artifacts)
    _, image_width = background.shape
    min_x = image_width // 2
    max_x = image_width - 2  # Crop right edge
    top_x, top_y = filter_film_rim_by_x_range(top_x, top_y, min_x, max_x)

    # Calculate mean plate height
    plate_height = float(np.mean(top_y))
    if not plate_height:
        raise ValueError("No valid plate height values found")

    # Save diagnostic visualization
    plt.figure()
    plt.imshow(background, cmap='gray', origin='lower')
    plt.scatter(top_x, top_y, s=1, color='green')
    plt.title(f"Plate Height: {plate_height:.1f} px")
    plt.savefig(output_dir / "background_plate_height.png")
    plt.close()

    return plate_height


if __name__ == "__main__":
    # Example usage: measure film height from captured images
    output_dir = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera"
    )

    # Step 1: Determine baseline plate height from background image
    background_path = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera\capture_20260622_152241.png"
    )
    plate_height_px = determine_plate_height(background_path, output_dir)
    print(f"Determined plate height: {plate_height_px:.1f} px")

    # Step 2: Measure film height from image with film layer
    image_path = Path(
        r"C:\CoughMachineData\260622_test_film_cough\260622_152201_VijfdeLaagje\camera\capture_20260622_152426.png"
    )
    film_height_px = determine_film_height(
        image_path, plate_height_px, output_dir)
    print(f"Determined film height: {film_height_px:.2f} px")

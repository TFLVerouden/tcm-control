"""Film height measurement from camera images."""

from pathlib import Path

import cv2
import numpy as np

# Film-height detection settings. Adjust these values to match the camera image.
IMAGE_CROP_LEFT = 120  # Ignore left-edge artifacts when measuring plate height.
CANNY_THR1 = 0  # Lower threshold for Canny edge detection.
CANNY_THR2 = 255  # Upper threshold for Canny edge detection.
PLATE_HEIGHT_CROSSING_TOLERANCE_PX = 1  # Allowed vertical distance from plate.
FILM_HEIGHT_RIGHTMOST_WIDTH_PX = 256  # Width used to average film height.
CONTACT_ANGLE_FIT_WIDTH_PX = 6  # Fit window extends this far right of contact.
REFERENCE_LINE_DASH_LENGTH_PX = 10
REFERENCE_LINE_GAP_LENGTH_PX = 5


def detect_film_rim(
    edge_x: np.ndarray,
    edge_y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the highest detected rim pixel at each x-coordinate.

    The image is vertically flipped before detection, so higher y-values
    correspond to higher points in the original image.
    """
    # Store one y-coordinate per image column; -1 marks columns with no edge.
    rim_y_by_x = np.full(int(np.max(edge_x)) + 1, -1, dtype=np.int32)

    # Keep the largest y-coordinate in each column, which is the upper rim
    # because callers flip the image so y increases upward.
    np.maximum.at(rim_y_by_x, edge_x, edge_y)

    # Return only columns where an edge was detected.
    rim_x = np.flatnonzero(rim_y_by_x >= 0)
    return rim_x, rim_y_by_x[rim_x]


def measure_film_properties(
    image_path: Path,
    plate_measurement: tuple[float, float, np.ndarray, np.ndarray, tuple[int, int]],
    scale_mm_per_px: float | None,
    output_dir: Path,
) -> tuple[float, float, float, float]:
    """Determine film thickness, its plate-derived error, and contact angle.

    Args:
        image_path: Path to the camera image file.
        plate_measurement: Plate height, standard deviation, rim coordinates,
            and image dimensions returned by measure_plate_height.
        scale_mm_per_px: Camera calibration in millimetres per pixel.
        output_dir: Directory to save visualization.

    Returns:
        Film thickness and plate-derived standard deviation in mm, acute
        contact angle in degrees, and mean film level in pixels.
    """
    original_image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if original_image is None:
        raise FileNotFoundError(f"Image not found at path: {image_path}")
    measurement, visualization = measure_film_frame(
        original_image, plate_measurement, scale_mm_per_px)
    visualization_path = output_dir / f"{image_path.stem}_processed.png"
    if not cv2.imwrite(str(visualization_path), visualization):
        raise OSError(f"Failed to save visualization to: {visualization_path}")
    return measurement


def measure_film_frame(
    original_image: np.ndarray,
    plate_measurement: tuple[float, float, np.ndarray, np.ndarray, tuple[int, int]],
    scale_mm_per_px: float | None,
) -> tuple[tuple[float, float, float, float], np.ndarray]:
    """Measure and annotate an 8-bit grayscale frame without saving it."""
    if (
        scale_mm_per_px is None
        or not np.isfinite(scale_mm_per_px)
        or scale_mm_per_px <= 0
    ):
        raise ValueError("Camera scale_mm_per_px must be a positive finite value")
    plate_height, plate_std, plate_x, plate_y, plate_shape = plate_measurement
    if original_image.shape != plate_shape:
        raise ValueError(
            f"Film image shape {original_image.shape} does not match "
            f"plate image shape {plate_shape}"
        )
    image = original_image[::-1, :]

    # Detect the upper film rim from the Canny edges.
    edge_map = cv2.Canny(image, CANNY_THR1, CANNY_THR2)
    edge_y, edge_x = np.where(edge_map != 0)
    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")
    rim_x, rim_y = detect_film_rim(edge_x, edge_y)

    # Find the rightmost rim point within the plate-height tolerance.
    _, image_width = image.shape
    crossing_indices = np.flatnonzero(
        np.abs(rim_y - plate_height) <= PLATE_HEIGHT_CROSSING_TOLERANCE_PX
    )
    if crossing_indices.size == 0:
        raise ValueError("Film contour does not cross the plate height")
    contact_index = int(crossing_indices[-1])
    contact_x = int(rim_x[contact_index])

    # Average the detected rim points in the rightmost configured columns.
    height_start_x = image_width - FILM_HEIGHT_RIGHTMOST_WIDTH_PX
    height_mask = rim_x >= height_start_x
    if not np.any(height_mask):
        raise ValueError("No contour points in the configured film-height range")
    film_height_px = float(np.mean(rim_y[height_mask]))
    thickness_mm = (film_height_px - plate_height) * scale_mm_per_px
    thickness_error_mm = plate_std * scale_mm_per_px

    # Fit the contour to the right of contact and convert its slope to an
    # acute angle relative to the horizontal plate.
    fit_mask = (
        (rim_x >= contact_x)
        & (rim_x <= contact_x + CONTACT_ANGLE_FIT_WIDTH_PX)
    )
    fit_x = rim_x[fit_mask]
    fit_y = rim_y[fit_mask]
    if fit_x.size < 2:
        raise ValueError("Not enough contour points to determine contact angle")
    slope, intercept = np.polyfit(fit_x, fit_y, 1)
    contact_angle_deg = float(np.degrees(np.arctan(abs(slope))))

    # Draw annotations on the unflipped source image so the output has the
    # same orientation and pixel dimensions as the camera image.
    visualization = cv2.cvtColor(original_image, cv2.COLOR_GRAY2BGR)

    # Draw the full film rim in blue and the measured plate rim in green.
    rim_points = np.column_stack(
        (rim_x, image.shape[0] - 1 - rim_y)
    ).astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(
        visualization, [rim_points], False, (255, 0, 0), 1, cv2.LINE_8
    )
    plate_points = np.column_stack(
        (plate_x, image.shape[0] - 1 - plate_y)
    ).astype(np.int32).reshape((-1, 1, 2))
    cv2.polylines(
        visualization, [plate_points], False, (0, 255, 0), 1, cv2.LINE_8
    )

    # Draw dashed white lines at the mean plate and film levels.
    plate_level_y = image.shape[0] - 1 - int(round(plate_height))
    film_level_y = image.shape[0] - 1 - int(round(film_height_px))
    for level_y, start_x in (
        (plate_level_y, 0),
        (film_level_y, max(0, height_start_x)),
    ):
        for x in range(
            start_x, image_width,
            REFERENCE_LINE_DASH_LENGTH_PX + REFERENCE_LINE_GAP_LENGTH_PX,
        ):
            cv2.line(
                visualization, (x, level_y),
                (min(x + REFERENCE_LINE_DASH_LENGTH_PX - 1, image_width - 1), level_y),
                (255, 255, 255), 1, cv2.LINE_8,
            )

    # Extend the fitted contact-angle line to the image boundaries. OpenCV
    # clips its endpoints where the line intersects the top or bottom edge.
    fit_y_left = image.shape[0] - 1 - int(round(intercept))
    fit_y_right = image.shape[0] - 1 - int(
        round(slope * (image_width - 1) + intercept)
    )
    cv2.line(
        visualization, (0, fit_y_left), (image_width - 1, fit_y_right),
        (0, 0, 255), 1, cv2.LINE_8,
    )

    # Show pixel levels, the plate's standard deviation, thickness in mm and
    # the contact angle. The error represents only variation in the plate rim.
    labels = (
        f"Plate: {plate_height:.2f} +/- {plate_std:.2f} px",
        f"Film level: {film_height_px:.2f} px",
        f"Film thickness: {thickness_mm:.3f} +/- {thickness_error_mm:.3f} mm",
        f"Contact angle: {contact_angle_deg:.1f} deg",
    )
    for line, label in enumerate(labels):
        cv2.putText(
            visualization, label, (10, 25 + line * 25),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_8,
        )

    return (thickness_mm, thickness_error_mm, contact_angle_deg, film_height_px), visualization



def measure_plate_height(
    background_path: Path,
) -> tuple[float, float, np.ndarray, np.ndarray, tuple[int, int]]:
    """Determine the plate height in pixels from a background image.

    Analyzes a background image (captured without the liquid film)
    to determine the baseline plate height position.

    Args:
        background_path: Path to the background image file.

    Returns:
        Mean height and standard deviation in pixels, rim x/y coordinates,
        and image shape for overlaying the rim on the film image.
    """
    # Retain the source image for its visualization while using a flipped copy
    # to make higher points have larger y-coordinates during detection.
    original_background = cv2.imread(
        str(background_path), cv2.IMREAD_GRAYSCALE
    )
    if original_background is None:
        raise RuntimeError(
            f"Failed to read captured image from: {background_path}"
        )
    background = original_background[::-1, :]

    # Detect edges and reduce them to one upper-rim point per image column.
    edge_map = cv2.Canny(background, CANNY_THR1, CANNY_THR2)
    edge_y, edge_x = np.where(edge_map != 0)

    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")

    top_x, top_y = detect_film_rim(edge_x, edge_y)

    # Exclude only the configured left-edge artifact region; use the rest of
    # the image width to calculate the baseline plate height.
    image_height, image_width = background.shape
    included = (top_x >= IMAGE_CROP_LEFT) & (top_x < image_width)
    top_x, top_y = top_x[included], top_y[included]
    if top_y.size == 0:
        raise ValueError("No valid plate height values found")

    # Use the standard deviation of the detected plate rim as the error in
    # plate height; this does not include uncertainty in the film or scale.
    plate_height = float(np.mean(top_y))
    plate_std = float(np.std(top_y))

    return plate_height, plate_std, top_x, top_y, (image_height, image_width)


if __name__ == "__main__":
    from tcm_control.devices.camera import DEFAULT_SCALE_MM_PER_PX
    # Example usage: measure film height from captured images
    output_dir = Path(
        r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp"
    )

    # Step 1: Determine baseline plate height from background image
    background_path = Path(
        r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/empty_261123_154407.tif"
    )
    plate_measurement = measure_plate_height(background_path)
    plate_height_px, plate_std_px, _, _, _ = plate_measurement
    print(f"Determined plate height: {plate_height_px:.1f} +/- {plate_std_px:.1f} px")

    # Step 2: Measure film height from image with film layer
    image_path = Path(
        r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/infuse_4mL.tif"
    )
    # Use the same camera calibration as the experiment configuration.
    scale_mm_per_px = DEFAULT_SCALE_MM_PER_PX
    film_height_mm, film_error_mm, contact_angle_deg, film_level_px = measure_film_properties(
        image_path, plate_measurement, scale_mm_per_px, output_dir)
    print(f"Determined film level: {film_level_px:.2f} px")
    print(f"Determined film height: {film_height_mm:.3f} +/- {film_error_mm:.3f} mm")
    print(f"Determined contact angle: {contact_angle_deg:.2f} deg")

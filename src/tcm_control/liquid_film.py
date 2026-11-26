"""Create liquid films and measure their height from camera images."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.filters import threshold_minimum

from tcm_control.devices.camera import Camera, validate_roi
from tcm_control.devices.cough_machine import CoughMachine
from tcm_control.devices.syringe_pump import SyringePump
from tcm_utils.io_utils import wait_with_progress

if TYPE_CHECKING:
    from tcm_control.imaging import LayerPreview

# Film-height detection settings. Adjust these values to match the camera image.
IMAGE_CROP_LEFT = 120
CANNY_THR1 = 0  # Lower threshold for Canny edge detection.
CANNY_THR2 = 255  # Upper threshold for Canny edge detection.
PLATE_HEIGHT_CROSSING_TOLERANCE_PX = 1  # Allowed vertical distance from plate.
FILM_HEIGHT_RIGHTMOST_WIDTH_PX = 256  # Width used to average film height.
# Image coordinates: y_start, y_end, x_start, x_end.
CONTACT_POINT_ROI = (256, -64, 12, 512)
# Suppress differences near the dark background.
PLATE_BACKGROUND_EXTENSION_PX = 1
CONTACT_ANGLE_FIT_WIDTH_PX = 6  # Fit window extends this far right of contact.

PlateMeasurement = tuple[
    float, float, np.ndarray, np.ndarray, tuple[int, int], np.ndarray
]


@lru_cache(maxsize=2)
def _film_label_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = files("tcm_utils").joinpath("fonts", "PTSans-Regular.ttf")
    return ImageFont.truetype(str(font_path), size=size)


# ------------------------------------------------------------------------------
# Film creation
# ------------------------------------------------------------------------------

def make_liquid_film(
    pump: SyringePump,
    camera: Camera,
    tcm: CoughMachine,
    infuse_volume_ml: float,
    infuse_rate_ml_min: float,
    withdraw_volume_ml: float,
    withdraw_rate_ml_min: float,
    settling_time_s: float,
    *,
    filename_prefix: str = "film",
    preview: LayerPreview | None = None,
) -> None:
    """Infuse, settle and withdraw, saving a snapshot after each step."""
    from tcm_control.imaging import take_snapshot, wait_with_preview

    update = preview.update if preview is not None else None

    # Helper function to create snapshot with specific name
    def snapshot(step: str) -> None:
        take_snapshot(
            camera, tcm, filename=f"{filename_prefix}_after_{step}",
            leave_light_on=preview is not None and preview.active,
        )

    # Infuse
    if not pump.infuse(
        volume_ml=infuse_volume_ml,
        rate_ml_min=infuse_rate_ml_min,
        update=update,
    ):
        raise RuntimeError("Layer creation aborted: infusion failed.")
    snapshot("infusion")

    # Wait for layer to settle
    if preview is None:
        wait_with_progress(wait_s=settling_time_s,
                           label="Waiting for layer to settle...",
                           )
    else:
        wait_with_preview(settling_time_s, preview)
    snapshot("settling")

    # Withdraw
    if not pump.withdraw(
        volume_ml=withdraw_volume_ml,
        rate_ml_min=withdraw_rate_ml_min,
        update=update,
    ):
        raise RuntimeError("Layer creation aborted: withdrawal failed.")
    snapshot("withdrawal")

    # Settle again
    if preview is None:
        wait_with_progress(wait_s=settling_time_s,
                           label="Waiting for layer to settle...",
                           )
    else:
        wait_with_preview(settling_time_s, preview)


# ------------------------------------------------------------------------------
# Film measurement
# ------------------------------------------------------------------------------

def measure_plate_height(
    background_path: Path,
) -> PlateMeasurement:
    """Determine the plate height in pixels from a background image.

    Analyzes a background image (captured without the liquid film)
    to determine the baseline plate height position.

    Args:
        background_path: Path to the background image file.

    Returns:
        Mean height and standard deviation in pixels, rim x/y coordinates,
        image shape, and the binarised background for subtraction.
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
    binary_background = binarise_image(original_background)
    background = binary_background[::-1, :]

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
    included_y = top_y[included]
    if included_y.size == 0:
        raise ValueError("No valid plate height values found")

    # Use the standard deviation of the detected plate rim as the error in
    # plate height; this does not include uncertainty in the film or scale.
    plate_height = float(np.mean(included_y))
    plate_std = float(np.std(included_y))

    # Warn if the standard deviation is large, which may indicate a dirty plate
    if plate_std > 2.0:
        print(
            f"Warning: Detected plate height has a large standard deviation "
            f"of {plate_std:.2f} px, which may indicate a dirty or uneven plate."
        )

    return (
        plate_height, plate_std, top_x, top_y,
        (image_height, image_width), binary_background,
    )


def measure_film_properties(
    image_path: Path,
    plate_measurement: PlateMeasurement,
    scale_mm_per_px: float | None,
    output_dir: Path,
    *,
    roi: tuple[int, int, int, int] = CONTACT_POINT_ROI,
) -> tuple[float, float, float, float]:
    """Determine film thickness, its plate-derived error, and contact angle.

    Args:
        image_path: Path to the camera image file.
        plate_measurement: Plate height, standard deviation, rim coordinates,
            and image dimensions returned by measure_plate_height.
        scale_mm_per_px: Camera calibration in millimetres per pixel.
        output_dir: Directory to save visualization.
        roi: Contact search area (y_start, y_end, x_start, x_end), in
            unflipped image coordinates. An end of zero means the image extent;
            a negative end is an offset from that extent.

    Returns:
        Film thickness and plate-derived standard deviation in mm, acute
        contact angle in degrees, and mean film level in pixels.
    """
    original_image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if original_image is None:
        raise FileNotFoundError(f"Image not found at path: {image_path}")
    measurement, visualization = measure_film_frame(
        original_image, plate_measurement, scale_mm_per_px, roi=roi)
    visualization_path = output_dir / f"{image_path.stem}_processed.png"
    if not cv2.imwrite(str(visualization_path), visualization):
        raise OSError(f"Failed to save visualization to: {visualization_path}")
    return measurement


def measure_film_frame(
    original_image: np.ndarray,
    plate_measurement: PlateMeasurement,
    scale_mm_per_px: float | None,
    *,
    show_binarised: bool = True,
    roi: tuple[int, int, int, int] = CONTACT_POINT_ROI,
) -> tuple[tuple[float, float, float, float], np.ndarray]:
    """Measure and annotate an 8-bit grayscale frame without saving it.

    The measurement uses the background-subtracted binary frame. The ROI uses
    unflipped image coordinates (y_start, y_end, x_start, x_end); zero ends
    mean the image extent and negative ends are offsets from it. Annotations
    are drawn on the subtracted frame, or on the original for the live preview.
    """
    if (
        scale_mm_per_px is None
        or not np.isfinite(scale_mm_per_px)
        or scale_mm_per_px <= 0
    ):
        raise ValueError(
            "Camera scale_mm_per_px must be a positive finite value")
    plate_height, plate_std, plate_x, plate_y, plate_shape, binary_background = (
        plate_measurement)
    if original_image.shape != plate_shape:
        raise ValueError(
            f"Film image shape {original_image.shape} does not match "
            f"plate image shape {plate_shape}"
        )
    binary_image = binarise_image(original_image)
    image_height, image_width = original_image.shape
    y_start, y_end, x_start, x_end = resolve_contact_roi(
        roi, original_image.shape)

    # Erode the bright background to extend dark plate features by the
    # configured distance, suppressing residual edges from small shifts.
    extension = PLATE_BACKGROUND_EXTENSION_PX
    if extension < 0:
        raise ValueError("Plate background extension must not be negative")
    kernel = np.ones((2 * extension + 1, 2 * extension + 1), dtype=np.uint8)
    extended_background = cv2.erode(binary_background, kernel)
    subtracted = cv2.subtract(extended_background, binary_image)
    image = subtracted[::-1, :]

    # Detect the upper film rim from the background-subtracted image.
    edge_map = cv2.Canny(image, CANNY_THR1, CANNY_THR2)
    edge_y, edge_x = np.where(edge_map != 0)
    if edge_x.size == 0:
        raise ValueError("No film-height edge pixels detected")
    rim_x, rim_y = detect_film_rim(edge_x, edge_y)

    # Restrict candidate rim points in the original, unflipped image space.
    original_y = image_height - 1 - rim_y
    in_roi = (
        (rim_x >= x_start) & (rim_x < x_end)
        & (original_y >= y_start) & (original_y < y_end)
    )
    contact_x, extrapolated_fit = find_contact_point(
        rim_x[in_roi], rim_y[in_roi], plate_height, plate_x, plate_y)

    # Average the detected rim points in the rightmost configured columns.
    height_start_x = image_width - FILM_HEIGHT_RIGHTMOST_WIDTH_PX
    height_mask = rim_x >= height_start_x
    if not np.any(height_mask):
        raise ValueError(
            "No contour points in the configured film-height range")
    film_height_px = float(np.mean(rim_y[height_mask]))
    thickness_mm = (film_height_px - plate_height) * scale_mm_per_px
    thickness_error_mm = plate_std * scale_mm_per_px

    # Fit the contour to the right of contact and convert its slope to an
    # acute angle relative to the horizontal plate.
    if extrapolated_fit is not None:
        slope, intercept = extrapolated_fit
    else:
        fit_mask = (
            (rim_x >= contact_x)
            & (rim_x <= contact_x + CONTACT_ANGLE_FIT_WIDTH_PX)
        )
        fit_x = rim_x[fit_mask]
        fit_y = rim_y[fit_mask]
        if fit_x.size < 2:
            raise ValueError(
                "Not enough contour points to determine contact angle")
        slope, intercept = np.polyfit(fit_x, fit_y, 1)
    contact_angle_deg = float(np.degrees(np.arctan(abs(slope))))

    # Draw annotations on the unflipped source image so the output has the
    # same orientation and pixel dimensions as the camera image.
    visualization = cv2.cvtColor(
        subtracted if show_binarised else original_image, cv2.COLOR_GRAY2BGR
    )

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

    dash_length_px = 10
    dash_gap_px = 5

    for level_y, start_x in (
        (plate_level_y, 0),
        (film_level_y, max(0, height_start_x)),
    ):
        for x in range(
            start_x, image_width,
            dash_length_px + dash_gap_px,
        ):
            cv2.line(
                visualization, (x, level_y),
                (min(x + dash_length_px - 1, image_width - 1), level_y),
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
        f"Plate: {plate_height:.2f} ± {plate_std:.2f} px",
        f"Film level: {film_height_px:.2f} px",
        f"Film thickness: {thickness_mm:.3f} ± {thickness_error_mm:.3f} mm",
        f"Contact angle: {contact_angle_deg:.1f} deg",
    )
    if show_binarised:
        grey = (128, 128, 128)
        cv2.rectangle(
            visualization, (x_start, y_start), (x_end - 1, y_end - 1),
            grey, 1, cv2.LINE_8,
        )

    # Outline the labels so they remain legible on either black or white.
    text_color = (255, 255, 255) if show_binarised else (255, 255, 0)
    visualization_rgb = Image.fromarray(
        cv2.cvtColor(visualization, cv2.COLOR_BGR2RGB)
    )
    draw = ImageDraw.Draw(visualization_rgb)
    label_font = _film_label_font(18)
    for line, label in enumerate(labels):
        draw.text(
            (10, 25 + line * 25),
            label,
            font=label_font,
            fill=text_color,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
            anchor="ls",
        )

    # Show the search rectangle only on saved processed images. The end
    # coordinates are exclusive, while OpenCV rectangle endpoints are inclusive.
    if show_binarised:
        draw.text(
            (x_start + 2, min(y_start + 15, y_end - 1)),
            "Contact ROI",
            font=_film_label_font(12),
            fill=(128, 128, 128),
            anchor="ls",
        )

    visualization = cv2.cvtColor(
        np.asarray(visualization_rgb), cv2.COLOR_RGB2BGR
    )
    return (thickness_mm, thickness_error_mm, contact_angle_deg, film_height_px), visualization


def find_contact_point(
    rim_x: np.ndarray,
    rim_y: np.ndarray,
    plate_height: float,
    plate_x: np.ndarray,
    plate_y: np.ndarray,
) -> tuple[int, tuple[float, float] | None]:
    """Find a rightmost plate crossing, or extrapolate the lowest film rim."""
    if rim_x.size == 0:
        raise ValueError("No contour points in the contact search range")

    # Prefer the rightmost film point near the mean plate level.
    tolerance = PLATE_HEIGHT_CROSSING_TOLERANCE_PX
    hits = np.flatnonzero(np.abs(rim_y - plate_height) <= tolerance)
    if hits.size:
        return int(np.max(rim_x[hits])), None

    # If the mean is not reached, compare only columns present in both rims.
    _, film_indices, plate_indices = np.intersect1d(
        rim_x, plate_x, assume_unique=True, return_indices=True
    )
    hits = np.flatnonzero(
        np.abs(rim_y[film_indices] - plate_y[plate_indices]) <= tolerance
    )
    if hits.size:
        return int(np.max(rim_x[film_indices[hits]])), None

    # Fit the lowest visible portion and extrapolate to the mean plate level.
    # The fitted intersection is deliberately not constrained to the ROI.
    start_x = rim_x[int(np.argmin(rim_y))]
    window = (rim_x >= start_x) & (
        rim_x <= start_x + CONTACT_ANGLE_FIT_WIDTH_PX)
    if np.count_nonzero(window) < 2:
        raise ValueError("Not enough contour points to extrapolate contact")
    slope, intercept = np.polyfit(rim_x[window], rim_y[window], 1)
    if np.isclose(slope, 0):
        raise ValueError("Cannot extrapolate a flat contour to the plate")
    return int(round((plate_height - intercept) / slope)), (slope, intercept)


def resolve_contact_roi(
    roi: tuple[int, int, int, int],
    shape: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Resolve and validate a contact ROI using the camera ROI convention."""
    y_start, y_end, x_start, x_end = validate_roi(roi)
    height, width = shape

    # A zero end means the full extent; a negative end counts from that extent.
    y_end = height if y_end == 0 else height + y_end if y_end < 0 else y_end
    x_end = width if x_end == 0 else width + x_end if x_end < 0 else x_end
    if not (0 <= y_start < y_end <= height and 0 <= x_start < x_end <= width):
        raise ValueError(
            f"ROI {roi} is empty or out of bounds for image size {height}x{width}.")
    return y_start, y_end, x_start, x_end


def binarise_image(image: np.ndarray) -> np.ndarray:
    """Return a 0/255 image thresholded at the histogram's minimum."""
    return ((image > threshold_minimum(image)) * 255).astype(np.uint8)


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


if __name__ == "__main__":
    from tcm_control.devices.camera import DEFAULT_SCALE_MM_PER_PX
    from skimage.filters import try_all_threshold
    # import matplotlib.pyplot as plt

    output_dir = Path(
        r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera"
    )
    img_list = [
        Path(r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera/261125_103914_empty_channel.tif"),
        Path(r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera/261125_103933_film_after_infusion.tif"),
        Path(r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera/261125_104003_film_after_settling.tif"),
        Path(r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera/261125_104037_film_after_withdrawal.tif"),
        Path(r"/Users/tommieverouden/Developer/twente-cough-machine/control/temp/camera/261125_104138_final_film.tif"),
    ]

    # # Compare different thresholding methods
    # img = cv2.imread(str(img_list[2]))
    # fig, ax = try_all_threshold(img, figsize=(10, 8), verbose=True)
    # plt.show()

    plate_measurement = measure_plate_height(img_list[0])
    plate_height_px, plate_std_px, *_ = plate_measurement
    print(
        f"Determined plate height: {plate_height_px:.1f} ± {plate_std_px:.1f} px")

    scale_mm_per_px = DEFAULT_SCALE_MM_PER_PX

    for img_path in img_list[1:]:

        film_height_mm, film_error_mm, contact_angle_deg, film_level_px = measure_film_properties(
            img_path, plate_measurement, scale_mm_per_px, output_dir)
        print(f"Determined film level: {film_level_px:.2f} px")
        print(
            f"Determined film height: {film_height_mm:.3f} ± {film_error_mm:.3f} mm")
        print(f"Determined contact angle: {contact_angle_deg:.2f} deg")

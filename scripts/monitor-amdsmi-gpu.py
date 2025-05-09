#!/usr/bin/env python3

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Monitor AMD GPU metrics at specified intervals.

This script collects and displays various GPU metrics including:
- Core and memory utilization
- Power consumption
- Activity periods
- Utilization counters

The data is collected at regular intervals and displayed in formatted tables
with deltas from previous measurements and min-max ranges.

Usage:
    python monitor-amdsmi-gpu.py INTERVAL DURATION

Arguments:
    INTERVAL            Time between measurements in seconds (eg: 5)
    DURATION            Duration in seconds to monitor GPU activity (eg: 60)
"""

import argparse
import json
import sys
import time
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

from amdsmi import (
    AmdSmiException,
    AmdSmiUtilizationCounterType,
    amdsmi_get_gpu_activity,
    amdsmi_get_gpu_asic_info,
    amdsmi_get_power_info,
    amdsmi_get_processor_handles,
    amdsmi_get_utilization_count,
    amdsmi_init,
    amdsmi_shut_down,
)


# Type definitions for better type checking
class GpuActivity(TypedDict):
    gfx_activity: float
    umc_activity: float


class PowerMeasure(TypedDict):
    current_socket_power: float


class GpuData(TypedDict):
    power_measure: PowerMeasure
    gpu_activity: GpuActivity
    utilization: List[Dict[str, Any]]


# Constants for GPU activity analysis
class ActivityThresholds:
    CORE_USE = 5  # 5% core utilization threshold
    MEM_USE = 5  # 5% memory utilization threshold
    POWER_INCREASE = 10  # 10W increase from baseline threshold
    MIN_INACTIVE_POINTS = 1  # Consecutive inactive points to end activity period


class DisplaySettings:
    MIN_BAR_LENGTH = 64  # Minimum length for title bars
    MAX_DELTA_POINTS = 12  # Maximum points to show deltas for


# Exit codes
class ExitCodes:
    SUCCESS = 0
    NO_GPU = 1
    INVALID_ARGS = 2
    LIBRARY_ERROR = 3
    RUNTIME_ERROR = 4


def format_number(value: Union[int, float], is_percentage: bool = False) -> str:
    """Format a number with appropriate units (K, M) or percentage."""
    if not isinstance(value, (int, float)):
        return str(value)

    if is_percentage:
        return f"{round(value)}%"
    elif abs(value) >= 1_000_000:
        return f"{round(value/1_000_000)}M"
    elif abs(value) >= 1_000:
        return f"{round(value/1_000)}K"
    else:
        return f"{round(value)}"


def calculate_delta(
    initial: Union[int, float],
    final: Union[int, float],
    is_percentage: bool = False,
    show_delta: bool = True,
) -> str:
    """
    Calculates and formats the difference between two values, with optional percentage formatting.
    Returns a string showing final value and delta (e.g. "100 (+20)" or "100%").
    """
    if not isinstance(initial, (int, float)) or not isinstance(final, (int, float)):
        return f"{initial} -> {final}"

    if is_percentage:
        return f"{format_number(final, is_percentage=True)}"

    if show_delta:
        delta = final - initial
        delta_str = format_number(delta, is_percentage)
        if delta > 0:
            delta_str = f"+{delta_str}"
        return f"{format_number(final, is_percentage)} ({delta_str})"

    return f"{format_number(final, is_percentage)}"


def calculate_min_max_range(
    values: List[Union[int, float]],
) -> Tuple[str, Union[int, float, str]]:
    numeric_values = [v for v in values if isinstance(v, (int, float))]
    if not numeric_values:
        return "N/A", "N/A"

    min_val = min(numeric_values)
    max_val = max(numeric_values)
    return f"{min_val} - {max_val}", max_val - min_val


def format_table(
    headers: List[str], data: List[List[Any]], min_widths: Optional[List[int]] = None
) -> str:
    """
    Creates a formatted ASCII table with aligned columns.
    Handles dynamic column widths based on content, with optional minimum widths.
    Returns a multi-line string with headers, separator, and data rows.
    """
    # Convert all data to strings and calculate column widths
    col_widths = [len(str(h)) for h in headers]
    str_data = []
    for row in data:
        str_row = [
            json.dumps(cell) if isinstance(cell, dict) else str(cell) for cell in row
        ]
        str_data.append(str_row)
        col_widths = [max(width, len(cell)) for width, cell in zip(col_widths, str_row)]

    # Apply minimum widths if provided
    if min_widths:
        col_widths = [
            max(width, min_width) for width, min_width in zip(col_widths, min_widths)
        ]

    # Create format string and separator
    format_str = " | ".join(f"{{:<{width}}}" for width in col_widths)
    separator = "-+-".join("-" * width for width in col_widths)

    # Build table
    table = [
        " " + format_str.format(*headers),
        " " + separator,
        *[" " + format_str.format(*row) for row in str_data],
    ]

    return "\n".join(table)


def print_title(title_text: str) -> None:
    title_length = max(len(title_text) + 2, DisplaySettings.MIN_BAR_LENGTH)
    print("=" * title_length)
    print(f" {title_text}")
    print("=" * title_length)


def print_table(
    title_text: str,
    headers: List[str],
    data: List[List[Any]],
    min_widths: Optional[List[int]] = None,
) -> None:
    print_title(title_text)
    print(format_table(headers, data, min_widths))


def collect_gpu_data(device: Any) -> GpuData:
    """
    Collects comprehensive GPU metrics including power, activity, and utilization data.
    Returns a dictionary containing current socket power, GPU activity (gfx/memory),
    and various utilization counters for both coarse and fine-grained metrics.
    """
    power_measure = amdsmi_get_power_info(device)
    gpu_activity = amdsmi_get_gpu_activity(device)
    utilization = amdsmi_get_utilization_count(
        device,
        [
            AmdSmiUtilizationCounterType.COARSE_GRAIN_GFX_ACTIVITY,
            AmdSmiUtilizationCounterType.COARSE_GRAIN_MEM_ACTIVITY,
            AmdSmiUtilizationCounterType.FINE_GRAIN_GFX_ACTIVITY,
            AmdSmiUtilizationCounterType.FINE_GRAIN_MEM_ACTIVITY,
        ],
    )

    power_data: PowerMeasure = {
        "current_socket_power": float(power_measure["current_socket_power"]),
    }
    activity_data: GpuActivity = {
        "gfx_activity": float(gpu_activity["gfx_activity"]),
        "umc_activity": float(gpu_activity["umc_activity"]),
    }

    return {
        "power_measure": power_data,
        "gpu_activity": activity_data,
        "utilization": utilization,
    }


def analyze_gpu_activity(
    data_points: List[GpuData], initial_data: GpuData
) -> List[Tuple[int, int, float]]:
    """
    Analyzes GPU activity patterns over time to identify active intervals.
    Uses thresholds for core usage, memory usage, and power consumption to detect activity.
    Returns list of tuples containing (start_index, end_index, max_utilization) for each active period.
    """
    active_intervals = []
    current_interval_start = None
    inactive_count = 0

    # Get baseline power
    baseline_power = initial_data["power_measure"]["current_socket_power"]

    for i, point in enumerate(data_points):
        core_use = point["gpu_activity"]["gfx_activity"]
        mem_use = point["gpu_activity"]["umc_activity"]
        power = point["power_measure"]["current_socket_power"]

        # Check if GPU shows signs of activity
        is_active = (
            core_use > ActivityThresholds.CORE_USE
            or mem_use > ActivityThresholds.MEM_USE
            or power > baseline_power + ActivityThresholds.POWER_INCREASE
        )

        if is_active:
            inactive_count = 0
            if current_interval_start is None:
                current_interval_start = i
        else:
            inactive_count += 1
            if (
                current_interval_start is not None
                and inactive_count >= ActivityThresholds.MIN_INACTIVE_POINTS
            ):
                # Calculate max utilization during this interval
                max_util = max(
                    max(
                        point["gpu_activity"]["gfx_activity"]
                        for point in data_points[current_interval_start:i]
                    ),
                    max(
                        point["gpu_activity"]["umc_activity"]
                        for point in data_points[current_interval_start:i]
                    ),
                )
                active_intervals.append(
                    (
                        current_interval_start,
                        i - ActivityThresholds.MIN_INACTIVE_POINTS,
                        max_util,
                    )
                )
                current_interval_start = None

    # Handle case where GPU is still active at the end
    if current_interval_start is not None:
        # Calculate max utilization for the final interval
        max_util = max(
            max(
                point["gpu_activity"]["gfx_activity"]
                for point in data_points[current_interval_start:]
            ),
            max(
                point["gpu_activity"]["umc_activity"]
                for point in data_points[current_interval_start:]
            ),
        )
        active_intervals.append(
            (current_interval_start, len(data_points) - 1, max_util)
        )

    return active_intervals


def display_asic_and_deltas(
    device: Any,
    initial_data: GpuData,
    data_points: List[GpuData],
    interval: int,
    duration: int,
) -> None:
    """
    Displays comprehensive GPU metrics in formatted tables, including:
    - GPU hardware information (ASIC details)
    - Usage metrics over time (core, memory, power)
    - Action count tallies
    - Activity analysis

    All metrics show deltas from previous measurements and min-max ranges.
    """
    # Display ASIC INFO first
    asic_info = amdsmi_get_gpu_asic_info(device)
    asic_data = [
        ["Market Name", asic_info["market_name"]],
        ["Vendor ID", asic_info["vendor_id"]],
        ["Vendor Name", asic_info["vendor_name"]],
        ["Device ID", asic_info["device_id"]],
        ["Revision ID", asic_info["revision_id"]],
        ["VBIOS Version", asic_info["vbios_version"]],
    ]

    print("\nGPU Hardware Information:")
    print("-" * 50)
    for label, value in asic_data:
        print(f"{label:20s}: {value}")

    # Initialize tracking lists for min/max calculations
    power_values: List[float] = []
    activity_values: List[float] = []
    coarse_gfx_values: List[float] = []
    coarse_mem_values: List[float] = []
    fine_gfx_values: List[float] = []
    fine_mem_values: List[float] = []

    # Process each data point and calculate metrics
    previous_data = None
    for data in data_points:
        # Format power data
        power_metrics, power_range = format_power_data(
            data, previous_data, power_values
        )

        # Format activity data
        activity_metrics, activity_range = format_activity_data(
            data, previous_data, activity_values
        )

        # Format utilization data for each counter type
        coarse_gfx_metrics, coarse_gfx_range = format_utilization_data(
            data,
            previous_data,
            "COARSE_GRAIN_GFX_ACTIVITY",
            coarse_gfx_values,
        )

        coarse_mem_metrics, coarse_mem_range = format_utilization_data(
            data,
            previous_data,
            "COARSE_GRAIN_MEM_ACTIVITY",
            coarse_mem_values,
        )

        fine_gfx_metrics, fine_gfx_range = format_utilization_data(
            data,
            previous_data,
            "FINE_GRAIN_GFX_ACTIVITY",
            fine_gfx_values,
        )

        fine_mem_metrics, fine_mem_range = format_utilization_data(
            data,
            previous_data,
            "FINE_GRAIN_MEM_ACTIVITY",
            fine_mem_values,
        )

        previous_data = data

    # Display formatted metrics
    print(f"\nMetrics collected over {duration} seconds ({interval}s intervals):")
    print("-" * 50)

    metrics_data = [
        ["Power Usage (W)", *power_metrics, power_range],
        ["GPU Activity (%)", *activity_metrics, activity_range],
        ["Coarse GFX Activity", *coarse_gfx_metrics, coarse_gfx_range],
        ["Coarse Memory Activity", *coarse_mem_metrics, coarse_mem_range],
        ["Fine GFX Activity", *fine_gfx_metrics, fine_gfx_range],
        ["Fine Memory Activity", *fine_mem_metrics, fine_mem_range],
    ]

    headers = ["Metric", "Current", "Delta", "Min-Max Range", "Range Value"]
    col_widths = [25, 15, 15, 20, 15]

    # Print headers
    header_row = "".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * sum(col_widths))

    # Print metrics
    for row in metrics_data:
        formatted_row = "".join(f"{str(cell):<{w}}" for cell, w in zip(row, col_widths))
        print(formatted_row)

    # Activity Analysis
    print("\nActivity Analysis:")
    print("-" * 50)

    # Calculate percentage of time GPU was active
    active_samples = sum(1 for v in activity_values if float(v) > 0)
    total_samples = len(activity_values)
    active_percentage = (
        (active_samples / total_samples * 100) if total_samples > 0 else 0
    )

    print(f"GPU Active: {format_number(active_percentage, True)} of the time")
    print(f"Total Samples: {total_samples}")
    print()  # Blank line after analysis section


def format_activity_data(
    current_data: GpuData,
    previous_data: Optional[GpuData],
    activity_values: List[float],
) -> Tuple[List[str], str]:
    """Format GPU activity data with deltas and trends."""
    current_activity = float(current_data["gpu_activity"]["gfx_activity"])
    activity_values.append(current_activity)

    if previous_data:
        prev_activity = float(previous_data["gpu_activity"]["gfx_activity"])
        delta = format_delta_value(current_activity, prev_activity, True)
    else:
        delta = "N/A"

    min_max_range, range_value = calculate_min_max_range(activity_values)
    return [format_number(current_activity, True), delta, min_max_range], str(
        range_value
    )


def format_power_data(
    current_data: GpuData,
    previous_data: Optional[GpuData],
    power_values: List[float],
) -> Tuple[List[str], str]:
    """Format power consumption data with deltas and trends."""
    current_power = float(current_data["power_measure"]["current_socket_power"])
    power_values.append(current_power)

    if previous_data:
        prev_power = float(previous_data["power_measure"]["current_socket_power"])
        delta = format_delta_value(current_power, prev_power)
    else:
        delta = "N/A"

    min_max_range, range_value = calculate_min_max_range(power_values)
    return [format_number(current_power), delta, min_max_range], str(range_value)


def format_utilization_data(
    current_data: GpuData,
    previous_data: Optional[GpuData],
    counter_type: str,
    utilization_values: List[float],
) -> Tuple[List[str], str]:
    """Format utilization counter data with deltas and trends."""
    current_util = float(
        [u for u in current_data["utilization"] if u["counter_type"] == counter_type][
            0
        ]["value"]
    )
    utilization_values.append(current_util)

    if previous_data:
        prev_util = float(
            [
                u
                for u in previous_data["utilization"]
                if u["counter_type"] == counter_type
            ][0]["value"]
        )
        delta = format_delta_value(current_util, prev_util)
    else:
        delta = "N/A"

    min_max_range, range_value = calculate_min_max_range(utilization_values)
    return [format_number(current_util), delta, min_max_range], str(range_value)


def format_delta_value(
    current: Union[int, float],
    previous: Union[int, float],
    is_percentage: bool = False,
) -> str:
    """Format the delta between current and previous values."""
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return "N/A"

    delta = current - previous
    sign = "+" if delta > 0 else ""
    return f"{sign}{format_number(delta, is_percentage)}"


def main() -> int:
    """Main function to monitor GPU metrics."""
    parser = argparse.ArgumentParser(
        description="Monitor AMD GPU metrics at specified intervals."
    )
    parser.add_argument(
        "interval",
        type=int,
        help="Time between measurements in seconds (eg: 5)",
    )
    parser.add_argument(
        "duration",
        type=int,
        help="Duration in seconds to monitor GPU activity (eg: 60)",
    )
    args = parser.parse_args()

    try:
        amdsmi_init()
        devices = amdsmi_get_processor_handles()

        if not devices:
            print("No AMD GPUs found.")
            return 1

        device = devices[0]  # Monitor the first GPU
        data_points: List[GpuData] = []

        # Collect initial data
        initial_data = collect_gpu_data(device)
        data_points.append(initial_data)

        # Collect data at specified intervals
        start_time = time.time()
        while time.time() - start_time < args.duration:
            time.sleep(args.interval)
            try:
                data = collect_gpu_data(device)
                data_points.append(data)
            except AmdSmiException as e:
                print(f"Error collecting GPU data: {e}")
                continue

        # Display results
        display_asic_and_deltas(
            device, initial_data, data_points, args.interval, args.duration
        )
        return 0

    except AmdSmiException as e:
        print(f"Error: {e}")
        return 1
    finally:
        amdsmi_shut_down()


if __name__ == "__main__":
    sys.exit(main())

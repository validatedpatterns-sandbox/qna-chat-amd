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
Prerequisites:
    - Python 3.x
    - amdsmi Python package (for AMD GPU monitoring)
    - AMD GPU with ROCm support

Useful for:
oc rsync to kserve_container of inference pod, oc rsh to pod, run to view gpu metrics

Usage:
    python3 monitor-amdsmi-gpu.py [-h] [-i INTERVAL] [-d DURATION]

    -h, --help            show this help message and exit
    -i INTERVAL, --interval INTERVAL
                            Interval in seconds between GPU measurements (eg: 5)
    -d DURATION, --duration DURATION
                            Duration in seconds to monitor GPU activity (eg: 60)
"""

import json
import time
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional, Union, TypedDict
import sys
import argparse
from amdsmi import (
    amdsmi_init, amdsmi_shut_down, amdsmi_get_processor_handles,
    amdsmi_get_gpu_asic_info, amdsmi_get_power_info,
    amdsmi_get_gpu_activity, amdsmi_get_utilization_count,
    AmdSmiException, AmdSmiUtilizationCounterType
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
    MEM_USE = 5   # 5% memory utilization threshold
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

def format_number(value: float, is_percentage: bool = False) -> str:
    """Format a number with appropriate units (K, M) or percentage."""
    if is_percentage:
        return f"{round(value)}%"
    if abs(value) >= 1_000_000:
        return f"{round(value/1_000_000)}M"
    elif abs(value) >= 1_000:
        return f"{round(value/1_000)}K"
    else:
        return f"{round(value)}"

def calculate_delta(initial: Union[int, float], final: Union[int, float], 
                   is_percentage: bool = False, show_delta: bool = True) -> str:
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

def calculate_min_max_range(values: List[Union[int, float]]) -> Tuple[str, Union[int, float]]:
    numeric_values = [v for v in values if isinstance(v, (int, float))]
    if not numeric_values:
        return "N/A", "N/A"
        
    min_val = min(numeric_values)
    max_val = max(numeric_values)
    return f"{min_val} - {max_val}", max_val - min_val

def format_table(headers: List[str], data: List[List[Any]], 
                min_widths: Optional[List[int]] = None) -> str:
    """
    Creates a formatted ASCII table with aligned columns.
    Handles dynamic column widths based on content, with optional minimum widths.
    Returns a multi-line string with headers, separator, and data rows.
    """
    # Convert all data to strings and calculate column widths
    col_widths = [len(str(h)) for h in headers]
    str_data = []
    for row in data:
        str_row = [json.dumps(cell) if isinstance(cell, dict) else str(cell) for cell in row]
        str_data.append(str_row)
        col_widths = [max(width, len(cell)) for width, cell in zip(col_widths, str_row)]
    
    # Apply minimum widths if provided
    if min_widths:
        col_widths = [max(width, min_width) for width, min_width in zip(col_widths, min_widths)]
    
    # Create format string and separator
    format_str = " | ".join(f"{{:<{width}}}" for width in col_widths)
    separator = "-+-".join("-" * width for width in col_widths)
    
    # Build table
    table = [
        " " + format_str.format(*headers),
        " " + separator,
        *[" " + format_str.format(*row) for row in str_data]
    ]
    
    return "\n".join(table)

def print_title(title_text: str) -> None:
    title_length = max(len(title_text) + 2, DisplaySettings.MIN_BAR_LENGTH)
    print("=" * title_length)
    print(f" {title_text}")
    print("=" * title_length)

def print_table(title_text: str, headers: List[str], 
               data: List[List[Any]], min_widths: Optional[List[int]] = None) -> None:
    print_title(title_text)
    print(format_table(headers, data, min_widths))

def collect_gpu_data(device: Any) -> GpuData:
    """
    Collects comprehensive GPU metrics including power, activity, and utilization data.
    Returns a dictionary containing current socket power, GPU activity (gfx/memory),
    and various utilization counters for both coarse and fine-grained metrics.
    """
    # Power measurements
    power_measure = amdsmi_get_power_info(device)
    
    # GPU activity
    gpu_activity = amdsmi_get_gpu_activity(device)
    
    # Utilization counts
    utilization = amdsmi_get_utilization_count(
        device,
        [AmdSmiUtilizationCounterType.COARSE_GRAIN_GFX_ACTIVITY,
         AmdSmiUtilizationCounterType.COARSE_GRAIN_MEM_ACTIVITY,
         AmdSmiUtilizationCounterType.FINE_GRAIN_GFX_ACTIVITY,
         AmdSmiUtilizationCounterType.FINE_GRAIN_MEM_ACTIVITY]
    )
    
    return {
        'power_measure': {
            'current_socket_power': power_measure['current_socket_power']
        },
        'gpu_activity': {
            'gfx_activity': gpu_activity['gfx_activity'],
            'umc_activity': gpu_activity['umc_activity']
        },
        'utilization': utilization
    }

def analyze_gpu_activity(data_points: List[GpuData], initial_data: GpuData) -> List[Tuple[int, int, float]]:
    """
    Analyzes GPU activity patterns over time to identify active intervals.
    Uses thresholds for core usage, memory usage, and power consumption to detect activity.
    Returns list of tuples containing (start_index, end_index, max_utilization) for each active period.
    """
    active_intervals = []
    current_interval_start = None
    inactive_count = 0
    
    # Get baseline power
    baseline_power = initial_data['power_measure']['current_socket_power']
    
    for i, point in enumerate(data_points):
        core_use = point['gpu_activity']['gfx_activity']
        mem_use = point['gpu_activity']['umc_activity']
        power = point['power_measure']['current_socket_power']
        
        # Check if GPU shows signs of activity
        is_active = (core_use > ActivityThresholds.CORE_USE or 
                    mem_use > ActivityThresholds.MEM_USE or 
                    power > baseline_power + ActivityThresholds.POWER_INCREASE)
        
        if is_active:
            inactive_count = 0
            if current_interval_start is None:
                current_interval_start = i
        else:
            inactive_count += 1
            if current_interval_start is not None and inactive_count >= ActivityThresholds.MIN_INACTIVE_POINTS:
                # Calculate max utilization during this interval
                max_util = max(
                    max(point['gpu_activity']['gfx_activity'] for point in data_points[current_interval_start:i]),
                    max(point['gpu_activity']['umc_activity'] for point in data_points[current_interval_start:i])
                )
                active_intervals.append((current_interval_start, i - ActivityThresholds.MIN_INACTIVE_POINTS, max_util))
                current_interval_start = None
    
    # Handle case where GPU is still active at the end
    if current_interval_start is not None:
        # Calculate max utilization for the final interval
        max_util = max(
            max(point['gpu_activity']['gfx_activity'] for point in data_points[current_interval_start:]),
            max(point['gpu_activity']['umc_activity'] for point in data_points[current_interval_start:])
        )
        active_intervals.append((current_interval_start, len(data_points) - 1, max_util))
    
    return active_intervals

def display_asic_and_deltas(device: Any, initial_data: GpuData, data_points: List[GpuData], 
                          interval: int, duration: int) -> None:
    """
    Displays comprehensive GPU metrics in formatted tables, including:
    - GPU hardware information (ASIC details)
    - Usage metrics over time (core, memory, power)
    - Action count tallies
    - Activity analysis showing periods of GPU utilization
    All metrics show deltas from previous measurements and min-max ranges.
    """
    # Display ASIC INFO first
    asic_info = amdsmi_get_gpu_asic_info(device)
    asic_data = [
        ["Market Name", asic_info['market_name']],
        ["Vendor ID", asic_info['vendor_id']],
        ["Vendor Name", asic_info['vendor_name']],
        ["Device ID", asic_info['device_id']],
        ["Revision ID", asic_info['rev_id']],
        ["ASIC Serial", asic_info['asic_serial']],
        ["OAM ID", asic_info['oam_id']],
        ["Target Graphics Version", asic_info['target_graphics_version']]
    ]
    
    # Calculate actual widths needed for GPU INFO table
    info_col1_width = max(len("Property"), max(len(row[0]) for row in asic_data))
    info_col2_width = max(len("Value"), max(len(str(row[1])) for row in asic_data))
    
    print_table("GPU INFO", ["Property", "Value"], asic_data, min_widths=[info_col1_width, info_col2_width])
    print()  # Single blank line between tables

    # Create headers for all time points
    num_points = len(data_points)
    # Generate time points up to duration
    time_points = [interval * (i + 1) for i in range(num_points) if interval * (i + 1) <= duration]
    headers = ["Seconds Elapsed"] + [f"{t}s" for t in time_points] + ["Min-Max Range", "Min-Max Δ"]
    
    # Determine if we should show deltas based on number of data points
    show_deltas = len(time_points) <= DisplaySettings.MAX_DELTA_POINTS
    
    # Combine all metrics into a single table
    all_metrics = []
    
    # GPU ACTIVITY - Gfx and Umc Activity (as percentages)
    activity_names = {
        'gfx_activity': 'GPU Core Use',
        'umc_activity': 'GPU Memory Use'
    }
    for key in ['gfx_activity', 'umc_activity']:
        row = [activity_names[key]]
        values = []
        prev_value = initial_data['gpu_activity'][key]
        values.append(prev_value)
        
        # Add all data points as deltas
        for i, point in enumerate(data_points):
            if interval * (i + 1) > duration:
                break
            current_value = point['gpu_activity'][key]
            values.append(current_value)
            row.append(calculate_delta(prev_value, current_value, is_percentage=True, show_delta=show_deltas))
            prev_value = current_value
        
        # Add min-max range and delta
        range_str, range_delta = calculate_min_max_range(values)
        row.append(f"{format_number(min(values), is_percentage=True)} - {format_number(max(values), is_percentage=True)}")
        row.append(format_number(range_delta, is_percentage=True))
        all_metrics.append(row)
    
    # POWER MEASUREMENTS - Current Socket Power
    key = 'current_socket_power'
    row = ["GPU Power Draw"]
    values = []
    prev_value = initial_data['power_measure'][key]
    values.append(prev_value)
    
    # Add all data points as deltas
    for i, point in enumerate(data_points):
        if interval * (i + 1) > duration:
            break
        current_value = point['power_measure'][key]
        values.append(current_value)
        # Format the current value with 'W' but keep delta without unit
        delta_str = calculate_delta(prev_value, current_value, show_delta=show_deltas)
        # Extract the delta part from parentheses and add it back
        if show_deltas:
            value_part = delta_str.split(' (')[0]
            delta_part = delta_str.split(' (')[1]
            row.append(f"{value_part}W ({delta_part}")
        else:
            row.append(f"{delta_str}W")
        prev_value = current_value
    
    # Add min-max range and delta
    range_str, range_delta = calculate_min_max_range(values)
    row.append(f"{format_number(min(values))}W - {format_number(max(values))}W")
    row.append(format_number(range_delta))
    all_metrics.append(row)
    
    # UTILIZATION COUNTS (as numerical values)
    util_metrics = []
    util_names = {
        'AMDSMI_COARSE_GRAIN_GFX_ACTIVITY': 'Graphics Actions (Coarse)',
        'AMDSMI_COARSE_GRAIN_MEM_ACTIVITY': 'Memory Actions (Coarse)',
        'AMDSMI_FINE_GRAIN_GFX_ACTIVITY': 'Graphics Actions (Fine)',
        'AMDSMI_FINE_GRAIN_MEM_ACTIVITY': 'Memory Actions (Fine)'
    }
    for item in data_points[-1]['utilization']:
        if isinstance(item, dict) and 'type' in item:
            util_type = util_names.get(item['type'], item['type'].replace('AMDSMI_', '').replace('_', ' ').title())
            values = []
            
            # Get initial value
            prev_value = next((x['value'] for x in initial_data['utilization'] 
                             if isinstance(x, dict) and x.get('type') == item['type']), None)
            if prev_value is not None:
                values.append(prev_value)
                row = [util_type]
                
                # Add all data points as deltas
                for i, point in enumerate(data_points):
                    if interval * (i + 1) > duration:
                        break
                    current_value = next((x['value'] for x in point['utilization'] 
                                        if isinstance(x, dict) and x.get('type') == item['type']), None)
                    if current_value is not None:
                        values.append(current_value)
                        row.append(calculate_delta(prev_value, current_value, show_delta=show_deltas))
                        prev_value = current_value
                
                # Add min-max range and delta
                range_str, range_delta = calculate_min_max_range(values)
                row.append(f"{format_number(min(values))} - {format_number(max(values))}")
                row.append(format_number(range_delta))
                util_metrics.append(row)
    
    # Calculate column widths from the utilization metrics table
    util_widths = [len(str(h)) for h in headers]
    for row in util_metrics:
        for i, cell in enumerate(row):
            util_widths[i] = max(util_widths[i], len(str(cell)))
    
    # Display tables with aligned columns
    print_table(f"GPU USAGE METRICS [taken every {interval}s for {duration}s]", headers, all_metrics, min_widths=util_widths)
    print()  # Single blank line between tables
    
    print_table("GPU ACTION COUNT TALLIES", headers, util_metrics)
    print()  # Single blank line after final table
    
    # Analyze and display GPU activity intervals
    active_intervals = analyze_gpu_activity(data_points, initial_data)
    
    print()  # Blank line before analysis section
    print_title(" GPU ACTIVITY ANALYSIS")
    
    if active_intervals:
        for start, end, max_util in active_intervals:
            start_time = (start + 1) * interval  # Convert to seconds
            end_time = (end + 1) * interval
            if start_time <= duration:  # Only show intervals within duration
                print(f"  • GPU active at {start_time}s through {end_time}s, peaking at {round(max_util)}% usage")
    else:
        print("  • No significant GPU activity detected during the monitoring period")
    
    print()  # Blank line after analysis section

def main() -> int:
    """Main function to run the GPU monitoring script."""
    parser = argparse.ArgumentParser(
        description='Monitor AMD GPU metrics at specified intervals.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python amdsmi_summary_graph.py 5 60    # Monitor every 5s for 60s
"""
    )
    parser.add_argument(
        'interval',
        type=int,
        help='Time between measurements in seconds'
    )
    parser.add_argument(
        'duration',
        type=int,
        help='Total monitoring duration in seconds'
    )
    
    # Add argument validation
    args = parser.parse_args()
    if args.interval < 3:
        parser.error("Interval greater than 2s recommended")
        return ExitCodes.INVALID_ARGS
    if args.duration > 300:
        parser.error("duration of less than 300s (5m) recommended")
        return ExitCodes.INVALID_ARGS
    if args.duration < args.interval:
        parser.error("Duration must be greater than or equal to interval")
        return ExitCodes.INVALID_ARGS 
    
    try:
        amdsmi_init()
        
        try:
            num_of_gpus = len(amdsmi_get_processor_handles())
            if num_of_gpus == 0:
                raise AmdSmiException("No GPUs detected on this system")
            
            for device in amdsmi_get_processor_handles():
                print(f"\nCollecting GPU activity metrics every {args.interval} seconds for {args.duration} seconds (wait)", end='', flush=True)
                
                # Collect initial data
                initial_data = collect_gpu_data(device)

                # Calculate number of data points needed
                if args.interval == 0:
                    raise ValueError("Interval cannot be zero")
                num_points = args.duration // args.interval  # Integer division to get exact number of points

                # Collect data at specified intervals
                data_points = []
                for i in range(num_points):
                    time.sleep(args.interval)
                    data_points.append(collect_gpu_data(device))
                    print(".", end='', flush=True)
                print("\n")  # Single blank line after collection message
                
                # Display all data points and deltas
                display_asic_and_deltas(device, initial_data, data_points, args.interval, args.duration)
                
        except AmdSmiException as e:
            print("Error: ", e)
            return ExitCodes.NO_GPU
        except ValueError as e:
            print("Error: ", e)
            return ExitCodes.INVALID_ARGS

    except AmdSmiException as e:
        print("Error: ", e)
        return ExitCodes.RUNTIME_ERROR
    finally:
        try:
            amdsmi_shut_down()
        except AmdSmiException as e:
            print("Error: ", e)
            return ExitCodes.RUNTIME_ERROR
    
    return ExitCodes.SUCCESS

if __name__ == "__main__":
    sys.exit(main())

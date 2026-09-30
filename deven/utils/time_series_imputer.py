# DevEN Path Bootstrapper
import sys
import os
import math
import numpy as np

"""
DevEN Time Series Imputation & Interpolation Engine
Provides 13+ robust missing data reconstruction & imputation algorithms for power system time series.
"""

def generate_time_points(duration=24.0, duration_unit="Hours", step_size=1.0, step_unit="Hours", start_time="2026-01-01 00:00:00"):
    """
    Generate chronological time index list and labels.
    Returns: list of dicts [{'index': int, 'time_hr': float, 'label': str, 'timestamp': str}]
    """
    unit_multipliers = {
        'seconds': 1.0 / 3600.0,
        'second': 1.0 / 3600.0,
        'minutes': 1.0 / 60.0,
        'minute': 1.0 / 60.0,
        'hours': 1.0,
        'hour': 1.0,
        'days': 24.0,
        'day': 24.0,
        'weeks': 168.0,
        'week': 168.0,
        'months': 730.0,
        'month': 730.0,
        'years': 8760.0,
        'year': 8760.0,
    }

    dur_mult = unit_multipliers.get(str(duration_unit).lower(), 1.0)
    step_mult = unit_multipliers.get(str(step_unit).lower(), 1.0)

    total_hours = float(duration) * dur_mult
    step_hours = float(step_size) * step_mult
    if step_hours <= 0:
        step_hours = 1.0

    n_steps = max(1, int(round(total_hours / step_hours)))
    
    # Try parsing start time
    from datetime import datetime, timedelta
    try:
        base_dt = datetime.strptime(str(start_time).strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        try:
            base_dt = datetime.strptime(str(start_time).strip(), "%Y-%m-%d %H:%M")
        except Exception:
            base_dt = datetime(2026, 1, 1, 0, 0, 0)

    points = []
    for i in range(n_steps):
        t_hr = i * step_hours
        dt = base_dt + timedelta(hours=t_hr)
        dt_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        # Label formatting based on duration
        if total_hours <= 48:
            lbl = dt.strftime("%H:%M")
        elif total_hours <= 336: # 2 weeks
            lbl = dt.strftime("%a %H:%M")
        elif total_hours <= 2000:
            lbl = dt.strftime("%b %d %H:%M")
        else:
            lbl = dt.strftime("%b %d")

        points.append({
            'index': i,
            'time_hr': t_hr,
            'label': lbl,
            'timestamp': dt_str
        })

    return points


def get_preset_profile(preset_name, n_steps=24, base_val=100.0):
    """
    Returns standard 24-step normalized curve multipliers (0.0 to 1.5) or scaled values.
    """
    preset_name = str(preset_name).lower()
    
    # 24-hour diurnal normalized shapes
    shapes = {
        'solar': [
            0.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.15, 0.40, 0.68, 0.88, 0.98, 1.00,
            0.98, 0.90, 0.72, 0.48, 0.22, 0.05, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        ],
        'wind': [
            0.85, 0.88, 0.92, 0.95, 0.90, 0.82, 0.75, 0.65, 0.55, 0.50, 0.48, 0.52,
            0.58, 0.62, 0.70, 0.78, 0.84, 0.89, 0.94, 0.96, 0.92, 0.88, 0.86, 0.84
        ],
        'residential': [
            0.45, 0.40, 0.38, 0.37, 0.42, 0.55, 0.75, 0.85, 0.72, 0.65, 0.60, 0.62,
            0.64, 0.62, 0.60, 0.65, 0.78, 0.95, 1.00, 0.98, 0.90, 0.78, 0.65, 0.52
        ],
        'commercial': [
            0.30, 0.28, 0.28, 0.28, 0.32, 0.45, 0.70, 0.90, 0.98, 1.00, 0.98, 0.95,
            0.95, 0.98, 0.96, 0.92, 0.85, 0.65, 0.48, 0.40, 0.35, 0.32, 0.30, 0.30
        ],
        'industrial': [
            0.85, 0.85, 0.84, 0.84, 0.88, 0.92, 0.95, 0.98, 1.00, 0.99, 0.98, 0.97,
            0.98, 0.99, 1.00, 0.98, 0.96, 0.95, 0.92, 0.90, 0.88, 0.87, 0.86, 0.85
        ],
        'peak_evening': [
            0.50, 0.45, 0.42, 0.40, 0.45, 0.55, 0.68, 0.72, 0.70, 0.68, 0.68, 0.70,
            0.70, 0.68, 0.68, 0.72, 0.82, 0.95, 1.00, 0.98, 0.90, 0.75, 0.62, 0.55
        ]
    }

    matched_shape = None
    for k, v in shapes.items():
        if k in preset_name:
            matched_shape = v
            break
    if matched_shape is None:
        matched_shape = shapes['residential']

    # Interpolate matched 24-point shape to requested n_steps
    x_orig = np.linspace(0, 1, len(matched_shape))
    x_new = np.linspace(0, 1, n_steps)
    interp_vals = np.interp(x_new, x_orig, matched_shape)
    
    return [float(v * base_val) for v in interp_vals]


class TimeSeriesImputer:
    """
    High-precision missing data imputer with 13 reconstruction methods.
    """

    SUPPORTED_METHODS = [
        ("linear",           "Linear Interpolation (Recommended)"),
        ("pchip",            "PCHIP Monotonic Cubic (Preserves Shape & Positivity)"),
        ("spline",           "Cubic Spline Interpolation"),
        ("polynomial",       "Polynomial Curve Fitting (Degree 2)"),
        ("time_based",       "Time-Weighted Timestamp Interpolation"),
        ("ffill",            "Forward Fill (Last Observation Carried Forward)"),
        ("bfill",            "Backward Fill (Next Observation Carried Backward)"),
        ("zero",             "Zero Fill (Missing = 0.0)"),
        ("mean",             "Mean Fill (Average of Known Profile Values)"),
        ("median",           "Median Fill (Median of Known Profile Values)"),
        ("constant_base",    "Constant Static Base-Case Value"),
        ("moving_avg",       "Moving Average Smoothing (Window = 3)"),
        ("exp_smooth",       "Exponential Smoothing (Alpha = 0.3)"),
        ("similar_day",      "Similar Day / Diurnal Pattern Scaling"),
    ]

    @staticmethod
    def impute_series(known_indices, known_values, total_steps, method="linear", default_base_val=100.0):
        """
        Impute full series of length total_steps from known (sparse) points.
        
        Args:
            known_indices (list of int): Time step indices where values are provided.
            known_values (list of float): Provided values.
            total_steps (int): Total length of the timeline.
            method (str): One of SUPPORTED_METHODS.
            default_base_val (float): Static fallback value if completely empty.

        Returns:
            list of float: Reconstructed full array of length total_steps.
        """
        if total_steps <= 0:
            return []

        # Case 1: Completely empty -> return constant default_base_val
        if not known_indices or not known_values or len(known_indices) == 0:
            return [float(default_base_val)] * total_steps

        # Clean and sort pairs
        pairs = sorted(zip(known_indices, known_values), key=lambda p: p[0])
        x_raw = []
        y_raw = []
        seen = set()
        for idx, val in pairs:
            if idx not in seen and 0 <= idx < total_steps and val is not None:
                try:
                    vf = float(val)
                    if not math.isnan(vf):
                        x_raw.append(int(idx))
                        y_raw.append(vf)
                        seen.add(idx)
                except (ValueError, TypeError):
                    pass

        if not x_raw:
            return [float(default_base_val)] * total_steps

        # Case 2: Only 1 known point -> broadcast or forward/backward fill
        if len(x_raw) == 1:
            return [float(y_raw[0])] * total_steps

        x = np.array(x_raw, dtype=float)
        y = np.array(y_raw, dtype=float)
        x_target = np.arange(total_steps, dtype=float)
        m = str(method).lower().strip()

        # ---------------------------------------------------------
        # Method 1: Linear Interpolation (with boundary hold)
        # ---------------------------------------------------------
        if m in ('linear', 'time_based'):
            y_out = np.interp(x_target, x, y)
            return [float(v) for v in y_out]

        # ---------------------------------------------------------
        # Method 2: PCHIP (Monotonic Cubic Hermite)
        # ---------------------------------------------------------
        elif m == 'pchip':
            try:
                from scipy.interpolate import PchipInterpolator
                pchip_fun = PchipInterpolator(x, y, extrapolate=True)
                y_out = pchip_fun(x_target)
                return [float(v) for v in y_out]
            except Exception:
                # Fallback to linear
                return [float(v) for v in np.interp(x_target, x, y)]

        # ---------------------------------------------------------
        # Method 3: Cubic Spline
        # ---------------------------------------------------------
        elif m == 'spline':
            try:
                from scipy.interpolate import CubicSpline
                if len(x) >= 4:
                    spline_fun = CubicSpline(x, y, extrapolate=True)
                    y_out = spline_fun(x_target)
                    return [float(v) for v in y_out]
                else:
                    return [float(v) for v in np.interp(x_target, x, y)]
            except Exception:
                return [float(v) for v in np.interp(x_target, x, y)]

        # ---------------------------------------------------------
        # Method 4: Polynomial Interpolation (Degree 2)
        # ---------------------------------------------------------
        elif m == 'polynomial':
            deg = min(2, len(x) - 1)
            poly_coefs = np.polyfit(x, y, deg)
            poly_fun = np.poly1d(poly_coefs)
            y_out = poly_fun(x_target)
            return [float(v) for v in y_out]

        # ---------------------------------------------------------
        # Method 5: Forward Fill (ffill)
        # ---------------------------------------------------------
        elif m == 'ffill':
            res = [None] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            last = y_raw[0]
            for i in range(total_steps):
                if res[i] is not None:
                    last = res[i]
                else:
                    res[i] = last
            return [float(v) for v in res]

        # ---------------------------------------------------------
        # Method 6: Backward Fill (bfill)
        # ---------------------------------------------------------
        elif m == 'bfill':
            res = [None] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            next_val = y_raw[-1]
            for i in range(total_steps - 1, -1, -1):
                if res[i] is not None:
                    next_val = res[i]
                else:
                    res[i] = next_val
            return [float(v) for v in res]

        # ---------------------------------------------------------
        # Method 7: Zero Fill
        # ---------------------------------------------------------
        elif m == 'zero':
            res = [0.0] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            return res

        # ---------------------------------------------------------
        # Method 8: Mean / Median Fill
        # ---------------------------------------------------------
        elif m == 'mean':
            avg_val = float(np.mean(y))
            res = [avg_val] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            return res

        elif m == 'median':
            med_val = float(np.median(y))
            res = [med_val] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            return res

        # ---------------------------------------------------------
        # Method 9: Constant Static Base Fill
        # ---------------------------------------------------------
        elif m == 'constant_base':
            res = [float(default_base_val)] * total_steps
            for idx, val in zip(x_raw, y_raw):
                res[idx] = val
            return res

        # ---------------------------------------------------------
        # Method 10: Moving Average
        # ---------------------------------------------------------
        elif m == 'moving_avg':
            # First linear interp, then rolling average window=3
            y_interp = np.interp(x_target, x, y)
            window = 3
            padded = np.pad(y_interp, (window//2, window//2), mode='edge')
            y_smooth = np.convolve(padded, np.ones(window)/window, mode='valid')
            return [float(v) for v in y_smooth[:total_steps]]

        # ---------------------------------------------------------
        # Method 11: Exponential Smoothing
        # ---------------------------------------------------------
        elif m == 'exp_smooth':
            y_interp = np.interp(x_target, x, y)
            alpha = 0.3
            y_exp = [y_interp[0]]
            for i in range(1, total_steps):
                y_exp.append(alpha * y_interp[i] + (1 - alpha) * y_exp[-1])
            return [float(v) for v in y_exp]

        # ---------------------------------------------------------
        # Method 12: Similar Day / Diurnal Pattern Scaling
        # ---------------------------------------------------------
        elif m == 'similar_day':
            # Scale diurnal shape to average known value
            avg_known = float(np.mean(y))
            preset_curve = get_preset_profile('residential', n_steps=total_steps, base_val=avg_known)
            # Anchor at known points
            y_interp = np.array(preset_curve)
            for idx, val in zip(x_raw, y_raw):
                y_interp[idx] = val
            return [float(v) for v in y_interp]

        # Default fallback: Linear
        y_out = np.interp(x_target, x, y)
        return [float(v) for v in y_out]

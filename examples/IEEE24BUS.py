"""
Power System Database - Exported from Editor
Generated: 2026-09-26 13:10:30
Contains: Buses, Generators, Loads, Lines, Transformers, Capacitors, Reactors, Series Comps, Series Reactors, Shunts
"""

MAP_SETTINGS = {}

SIMULATION_SETTINGS = {'v_init_mode': 'Flat Start (1.0 ∠ 0.0° p.u.)', 'engine': 'andes_nr', 'tol': 1e-06, 'max_iter': 20, 'ignore_q_tol': False, 'output_folder': '', 'variation': 10, 'samples': 200, 'ignore_islands': True, 'industry_std_pv': True, 'overwrite_results': True, 'pre_run_validate_db': False, 'auto_open_result_viewer': False, 'save_samples': False, 'ieee_report': True, 'cea_report': True, 'fb_enable_pipeline': True, 'fb_stage_max_iter': 20, 'fb_use_dc_angle': True, 'fb_use_q_delay': True, 'fb_use_step_damping': True, 'fb_use_lm': True, 'fb_use_homotopy': True, 'fb_use_diagnostics': True}

SOLVER_CONFIG = {'v_init_mode': 'Flat Start (1.0 ∠ 0.0° p.u.)', 'engine': 'andes_nr', 'tol': 1e-06, 'max_iter': 20, 'ignore_q_tol': False, 'output_folder': '', 'variation': 10, 'samples': 200, 'ignore_islands': True, 'industry_std_pv': True, 'overwrite_results': True, 'pre_run_validate_db': False, 'auto_open_result_viewer': False, 'save_samples': False, 'ieee_report': True, 'cea_report': True, 'fb_enable_pipeline': True, 'fb_stage_max_iter': 20, 'fb_use_dc_angle': True, 'fb_use_q_delay': True, 'fb_use_step_damping': True, 'fb_use_lm': True, 'fb_use_homotopy': True, 'fb_use_diagnostics': True}

BASE_MVA = 100.0

# ========== BUS DATA ==========
# [bus_num, bus_name, bus_type, base_kV, V_init_pu, angle_init_deg, shunt_G, shunt_B, area, zone, owner, lat, long, sk_mva, rx_ratio, z01_ratio]
BUS_DATA = [
    [1, "1", 3, 138.0, 1.0, 0.0, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [2, "2", 2, 138.0, 0.9978, 0.0103, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [3, "3", 1, 138.0, 0.8638, 10.7521, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [4, "4", 1, 138.0, 0.8871, -0.4151, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [5, "5", 1, 138.0, 0.9273, -0.229, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [6, "6", 1, 138.0, 0.908, 0.3919, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [7, "7", 2, 138.0, 0.7964, -0.5795, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [8, "8", 1, 230.0, 0.8055, -0.8676, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [9, "9", 1, 138.0, 0.835, 4.9872, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [10, "10", 1, 138.0, 0.8818, 3.722, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [11, "11", 1, 230.0, 0.8362, 12.6352, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [12, "12", 1, 230.0, 0.8399, 11.7784, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [13, "13", 2, 230.0, 0.837, 15.4438, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [14, "14", 2, 230.0, 0.8365, 18.7499, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [15, "15", 2, 230.0, 0.8853, 33.2005, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [16, "16", 2, 230.0, 0.8622, 27.0731, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [17, "17", 1, 230.0, 0.8958, 32.0488, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [18, "18", 2, 230.0, 0.9011, 33.8866, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [19, "19", 1, 230.0, 0.8519, 23.794, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [20, "20", 1, 230.0, 0.8495, 22.3217, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [21, "21", 2, 230.0, 0.9113, 35.645, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [22, "22", 2, 230.0, 1.0, 37.4898, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [23, "23", 2, 230.0, 0.8498, 22.0699, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
    [24, "24", 1, 230.0, 0.8551, 24.8036, 0, 0, 1, 1, 1, 0.0, 0.0, 1000.0, 0.1, 1.0],
]

# ========== GENERATOR DATA ==========
# [gen_num, gen_name, gen_type, bus, P_out, Q_out, V_set, Qmin, Qmax, status, area, zone, owner, R1_pu, X1_pu, R2_pu, X2_pu, R0_pu, X0_pu, cb_mva, wind_conn, gnd_r, gnd_x]
GENERATOR_DATA = [
    [1, "Gen_1_1", "SYNC", 1, 35.907, 180.304, 1.0, -9900.0, 9900.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [2, "Gen_2_1", "SYNC", 2, 67.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [3, "Gen_7_1", "SYNC", 7, 64.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [4, "Gen_13_1", "SYNC", 13, 200.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [5, "Gen_14_1", "SYNC", 14, 0.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [6, "Gen_15_1", "SYNC", 15, 274.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [7, "Gen_16_1", "SYNC", 16, 245.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [8, "Gen_18_1", "SYNC", 18, 144.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [9, "Gen_21_1", "SYNC", 21, 294.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [10, "Gen_22_1", "SYNC", 22, 150.0, 199.306, 1.0, -9900.0, 9900.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
    [11, "Gen_23_1", "SYNC", 23, 200.0, 0.0, 1.0, 0.0, 0.0, 1, 1, 1, 1, 100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, "0", 0.0, 0.0],
]

# ========== LOAD DATA ==========
# [load_num, load_name, bus, P_demand, Q_demand, model, area, zone, cb_mva, wind_conn]
LOAD_DATA = [
    [1, "Load_2_1", 2, 97.0, 20.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [2, "Load_3_1", 3, 90.0, 19.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [3, "Load_4_1", 4, 74.0, 15.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [4, "Load_5_1", 5, 71.0, 14.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [5, "Load_6_1", 6, 68.0, 14.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [6, "Load_7_1", 7, 62.0, 13.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [7, "Load_8_1", 8, 85.0, 18.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [8, "Load_9_1", 9, 175.0, 36.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [9, "Load_10_1", 10, 100.0, 23.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [10, "Load_13_1", 13, 130.0, 27.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [11, "Load_14_1", 14, 92.0, 20.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [12, "Load_15_1", 15, 158.0, 32.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [13, "Load_16_1", 16, 100.0, 20.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [14, "Load_18_1", 18, 162.0, 34.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [15, "Load_19_1", 19, 90.0, 18.0, "constant_PQ", 1, 1, 1500.0, "G"],
    [16, "Load_20_1", 20, 65.0, 13.0, "constant_PQ", 1, 1, 1500.0, "G"],
]

# ========== TRANSMISSION LINE DATA ==========
# [line_num, line_name, from_bus, to_bus, length_km, R_per_km, X_per_km, B_per_km, rateA, status, area, zone, owner, R0_per_km, X0_per_km, B0_per_km, from_cb_mva, to_cb_mva]
LINE_DATA = [
    [1, "Line_1_2", 1, 2, 1.0, 0.0007, 0.00123, 0.00065, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [2, "Line_1_3", 1, 3, 2.0, 0.027095, 0.10557, 0.03065, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [3, "Line_1_5", 1, 5, 1.0, 0.02243, 0.0849, 0.0244, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [4, "Line_2_4", 2, 4, 1.0, 0.03361, 0.1273, 0.0366, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [5, "Line_2_6", 2, 6, 1.0, 0.05064, 0.19201, 0.0557, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [6, "Line_3_9", 3, 9, 1.0, 0.03148, 0.11921, 0.0343, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [7, "Line_4_9", 4, 9, 1.0, 0.02692, 0.10779, 0.0279, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [8, "Line_6_10", 6, 10, 2.0, 0.01131, 0.016665, 0.065145, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [9, "Line_7_8", 7, 8, 1.0, 0.01614, 0.06103, 0.0179, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [10, "Line_8_9", 8, 9, 1.0, 0.04234, 0.16482, 0.0478, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [11, "Line_8_10", 8, 10, 1.0, 0.04234, 0.16482, 0.0478, 175.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [12, "Line_11_13", 11, 13, 1.0, 0.00583, 0.04746, 0.0959, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [13, "Line_11_14", 11, 14, 1.0, 0.00513, 0.04172, 0.0843, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [14, "Line_12_13", 12, 13, 1.0, 0.00583, 0.0476, 0.0959, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [15, "Line_12_23", 12, 23, 1.0, 0.01224, 0.09644, 0.1984, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [16, "Line_13_23", 13, 23, 2.0, 0.0053, 0.043215, 0.0876, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [17, "Line_14_16", 14, 16, 1.0, 0.00477, 0.03884, 0.0785, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [18, "Line_15_16", 15, 16, 2.0, 0.00106, 0.086345, 0.01745, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [19, "Line_15_21", 15, 21, 1.0, 0.00607, 0.04899, 0.1006, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [20, "Line_15_21_", 15, 21, 2.0, 0.003035, 0.024495, 0.0503, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [21, "Line_15_24", 15, 24, 1.0, 0.00642, 0.05187, 0.1066, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [22, "Line_16_17", 16, 17, 1.0, 0.00318, 0.0259, 0.0523, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [23, "Line_16_19", 16, 19, 1.0, 0.00283, 0.02302, 0.0465, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [24, "Line_17_18", 17, 18, 1.0, 0.00177, 0.01439, 0.0291, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [25, "Line_17_22", 17, 22, 1.0, 0.01225, 0.10527, 0.2116, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [26, "Line_18_21", 18, 21, 1.0, 0.00331, 0.02595, 0.0533, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [27, "Line_18_21_", 18, 21, 1.0, 0.00331, 0.02595, 0.0533, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [28, "Line_19_20", 19, 20, 1.0, 0.00505, 0.03964, 0.0814, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [29, "Line_19_20_", 19, 20, 1.0, 0.00505, 0.03964, 0.0814, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [30, "Line_20_23", 20, 23, 1.0, 0.00276, 0.02163, 0.0444, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [31, "Line_20_23_", 20, 23, 1.0, 0.00276, 0.02163, 0.0444, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [32, "Line_21_22", 21, 22, 1.0, 0.00829, 0.06769, 0.1367, 500.0, 1, 1, 1, 1, 0.0, 0.0, 0.0, 1500.0, 1500.0],
]

# ========== TRANSFORMER DATA ==========
# [xfmr_num, xfmr_name, from_bus, to_bus, R_pu, X_pu, tap_ratio, rateA, phase_shift, min_tap, max_tap, step_size, status, area, zone, owner, R0_pu, X0_pu, from_conn, to_conn, from_gnd_r, from_gnd_x, to_gnd_r, to_gnd_x, from_cb_mva, to_cb_mva]
TRANSFORMER_DATA = [
    [1, "Xfmr_24_3", 24, 3, 0.0023, 0.0839, 1.0, 400.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [2, "Xfmr_5_10", 5, 10, 0.02334, 0.08837, 1.0, 175.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [3, "Xfmr_11_9", 11, 9, 0.0023, 0.0839, 1.0, 400.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [4, "Xfmr_9_12", 9, 12, 0.0023, 0.0839, 1.0, 400.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [5, "Xfmr_11_10", 11, 10, 0.0023, 0.0839, 1.0, 400.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
    [6, "Xfmr_12_10", 12, 10, 0.0023, 0.0839, 1.0, 400.0, 0.0, 0.51, 1.5, 0.0062, 1, 1, 1, 1, 0.0, 0.0, "0", "0", 0.0, 0.0, 0.0, 0.0, 1500.0, 1500.0],
]

# ========== THREE-WINDING TRANSFORMER DATA ==========
# [tw_num, tw_name, hv_bus, mv_bus, lv_bus, r_hm, x_hm, r_hl, x_hl, r_ml, x_ml, rate_h, rate_m, rate_l, tap_h, tap_m, tap_l, status, area, zone, owner]
THREE_WINDING_TRANSFORMER_DATA = [
]

# ========== CAPACITOR DATA ==========
# [cap_num, cap_name, bus, Q_cap, status, area, zone]
CAPACITOR_DATA = [
]

# ========== REACTOR DATA ==========
# [reactor_num, reactor_name, bus, Q_react, status, area, zone, G1_pu, B1_pu, G0_pu, B0_pu, cb_mva]
REACTOR_DATA = [
]

# ========== SERIES COMPENSATION DATA ==========
# [series_num, series_name, from_bus, to_bus, r, x, comp_pct, status, area, zone, owner]
SERIES_COMP_DATA = [
]

# ========== SERIES REACTOR DATA ==========
# [sr_num, sr_name, from_bus, to_bus, r, x, status, area, zone, owner]
SERIES_REACTOR_DATA = [
]

# ========== TWO-TERMINAL HVDC LINK DATA ==========
# [link_num, link_name, from_bus, to_bus, r_dc, status, from_mode, from_ctrl_type, from_val, from_angle, from_xc, from_tfr_kv, from_tfr_mva, from_tap_min, from_tap_max, from_tap_step, from_nb, from_np, to_mode, to_ctrl_type, to_val, to_angle, to_xc, to_tfr_kv, to_tfr_mva, to_tap_min, to_tap_max, to_tap_step, to_nb, to_np, area, zone, owner]
HVDC_LINK_DATA = [
]

# ========== SHUNT COMPENSATION DATA ==========
# [shunt_num, shunt_name, bus, Q_shunt, status, area, zone]
SHUNT_DATA = [
    [1, "FACTS_1_1", 1, 120.0, 1, 1, 1],
    [2, "FACTS_6_2", 6, 100.0, 1, 1, 1],
]

# ========== SHORT CIRCUIT FAULT CASES ==========
FAULT_ON_SELECTED_BUSES = []

# ========== TRANSMISSION LINE ZERO SEQUENCE FACTORS ==========
TRANSMISSION_LINE_ZERO_SEQ_FACTORS = []

# ========== GLOBAL SEQUENCE CORRECTION FACTORS ==========
GLOBAL_SEQUENCE_CORRECTION_FACTORS = {}

# ========== HARMONIC SOURCES (IEEE 519) ==========
HARMONIC_SOURCES = []

# ========== PASSIVE HARMONIC FILTERS ==========
HARMONIC_FILTERS = []

# ========== TIME SERIES LOAD FLOW SETTINGS & PROFILES ==========
TIME_SERIES_SETTINGS = {'duration': 24.0, 'duration_unit': 'Hours', 'step_size': 1.0, 'step_unit': 'Hours', 'start_time': '2026-01-01 00:00:00', 'imputation_method': 'linear', 'continue_on_divergence': True, 'auto_retry_flat_start': True}

TIME_SERIES_PROFILES = {'generators': {}, 'loads': {}, 'capacitors': {}, 'reactors': {}, 'shunts': {}}

# ========== GENERATOR ADVANCED PARAMETERS ==========
GENERATOR_ADVANCED_DATA = {}

# ========== TRANSFORMER ADVANCED PARAMETERS ==========
TRANSFORMER_ADVANCED_DATA = {}

# ========== SINGLE LINE DIAGRAMS (EMBEDDED) ==========
SLD_DIAGRAMS = {'Diagram 1': {'version': 3, 'paper_name': 'A3 Landscape', 'canvas_w': 1587, 'canvas_h': 1123, 'canvas_bg': '#ffffff', 'grid_color': '#eaeaea', 'grid_width': 1.0, 'grid_size': 4, 'voltage_levels': [{'kv': 765.0, 'color': '#A60038'}, {'kv': 400.0, 'color': '#C0392B'}, {'kv': 230.0, 'color': '#3F22E5'}, {'kv': 220.0, 'color': '#B7791F'}, {'kv': 138.0, 'color': '#22E522'}, {'kv': 132.0, 'color': '#B7950B'}, {'kv': 110.0, 'color': '#558B2F'}, {'kv': 66.0, 'color': '#1E8449'}, {'kv': 33.0, 'color': '#0E6655'}, {'kv': 22.0, 'color': '#006064'}, {'kv': 11.0, 'color': '#1565C0'}, {'kv': 6.6, 'color': '#0A387E'}, {'kv': 3.3, 'color': '#5B2C6F'}, {'kv': 0.415, 'color': '#880088'}], 'connected_db_path': 'E:/invlfa/N_Backup/DevEN_V4/DevEN_3.13/DevEN_PY/examples/IEEE24BUS_converted.py', 'sheet_settings': {'show_border': True, 'border_color': '#000000', 'border_width': 1.5, 'border_margin': 15, 'show_title_block': True, 'title_position': 'Bottom-Strip', 'company_name': 'POWER TRANSMISSION CORPORATION', 'project_name': 'DevEN Grid System', 'diagram_title': 'Diagram 1', 'author': 'Devaraj E', 'checked_by': 'Chief Engineer', 'case_description': 'BASE CASE', 'date_str': '11-09-2026 19:12:02', 'show_company': True, 'show_project': True, 'show_title': True, 'show_author': True, 'show_checked': True, 'show_date': True, 'show_case': True, 'title_bg_color': '', 'title_fg_color': '#000000', 'title_border_color': '#000000', 'show_legend': True, 'legend_position': 'Top-Left', 'show_voltage_legend': True, 'show_loading_legend': True, 'legend_bg_color': '', 'legend_fg_color': '#000000', 'legend_border_color': '#000000'}, 'buses': [], 'lines': [], 'xfmrs': [], '3wxfmrs': [], 'scs': [], 'srs': [], 'hvdcs': [], 'syms': [], 'annotations': []}}

if __name__ == "__main__":
    print(f"Buses: {len(BUS_DATA)}")
    print(f"Generators: {len(GENERATOR_DATA)}")
    print(f"Loads: {len(LOAD_DATA)}")
    print(f"Lines: {len(LINE_DATA)}")
    print(f"Transformers: {len(TRANSFORMER_DATA)}")
    print(f"Capacitors: {len(CAPACITOR_DATA)}")
    print(f"Reactors: {len(REACTOR_DATA)}")
    print(f"HVDC Links: {len(HVDC_LINK_DATA)}")
    print(f"Harmonic Sources: {len(HARMONIC_SOURCES)}")
    print(f"Harmonic Filters: {len(HARMONIC_FILTERS)}")
    print(f"Fault Cases: {len(FAULT_ON_SELECTED_BUSES)}")
    if "BESS_DATA" in locals(): print(f"BESS: {len(BESS_DATA)}")

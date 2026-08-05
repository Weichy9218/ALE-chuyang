# Goal

Calibrate the Catphan fan-beam CT geometry from the supplied sinogram, save the two required outputs at their exact paths, and achieve SSIM >= 0.95 and unnormalized MSE <= 4e-6 without modifying the input files or copying/blending the reference into the reconstruction.

# Current State

The required bundle is present and independently reproducible with the task's canonical Python/LEAP runtime. The calibrated reconstruction was replayed directly from `sinogram.npy` using the submitted JSON geometry and was byte-for-byte identical to `reconstructed_calibrated.npy`.

# Contract Acceptance State

- `reconstruct.py` was inspected: nominal fan-beam geometry is SAD 800 mm, SDD 1200 mm, detector offset 0 mm, 360 endpoint-excluded views over 360 degrees, 1024 detector elements at 1.0 mm, and a 512x512 volume at 0.8 mm.
- Nominal baseline was executed and independently measured: SSIM 0.38613049818871314; unnormalized MSE 1.8008568326527137e-05.
- Iterative calibration evidence is present: 352 finite three-parameter/tau evaluations and 43 finite extended-angle evaluations.
- Both exact required output paths exist with correct case/extensions and non-empty contents.
- `geometry_calibrated.json` parses as JSON and contains the complete geometry needed for replay.
- `reconstructed_calibrated.npy` parses without pickle, is float32 with shape 512x512, and contains only finite values.
- Independent final metrics are SSIM 0.9964346364141674 and unnormalized MSE 3.683554124722991e-08; both thresholds pass.
- JSON-reported metrics equal the independently recomputed metrics exactly.
- A fresh LEAP CPU FBP replay from the measured sinogram is array-equal to the submitted reconstruction with maximum absolute difference 0 and the same SHA-256 (`6648a0c1dad160970c868cf678d46eb09203e250602c889cf19567ea6a41a961`).
- The submitted reconstruction is not array-equal to the reference; replay provenance shows it is produced from the sinogram rather than copied or blended from the reference.
- Input files retain their original April 16, 2026 modification timestamps; inspected calibration and replay code read them without writing under `input/`.

# Calibrated Geometry

- SAD: 786.257 mm
- SDD: 1217.892 mm
- Detector offset: -1.9875 mm
- Tau: 0
- Angular start: -0.00498611111109426 degrees
- Angular range: 359.99 degrees across 360 endpoint-excluded views
- Angular step: -0.9999722222222223 degrees
- Flat detector, detector pitch 1.0 mm, voxel pitch 0.8 mm, ramp filter order 2

# Open Questions / Blockers

None.

# Required Outputs

- `/media/user/data/agenthle/health_medicine/ct_geometry_calibration_catphan/instance_1/output/geometry_calibrated.json`
- `/media/user/data/agenthle/health_medicine/ct_geometry_calibration_catphan/instance_1/output/reconstructed_calibrated.npy`

# Reviewer Evidence

- Independent replay and metric audit: `/home/user/.ale/argus/argus_full4__gpt-5-6-sol__health_medicine__ct_geometry_calibration_catphan__v0__20260724_182349/argus_home/projects/ale/audits/841005df55a6/round-0002-l2/independent_audit.json`
- Exact-path metadata and hashes: `/home/user/.ale/argus/argus_full4__gpt-5-6-sol__health_medicine__ct_geometry_calibration_catphan__v0__20260724_182349/argus_home/projects/ale/audits/841005df55a6/round-0002-l2/artifact_manifest.json`
- Fresh replay artifact: `/home/user/.ale/argus/argus_full4__gpt-5-6-sol__health_medicine__ct_geometry_calibration_catphan__v0__20260724_182349/argus_home/projects/ale/audits/841005df55a6/round-0002-l2/replayed_reconstructed_calibrated.npy`
- Calibration evaluation logs: `/media/user/data/agenthle/health_medicine/ct_geometry_calibration_catphan/instance_1/output/calibration_evaluations.csv` and `/media/user/data/agenthle/health_medicine/ct_geometry_calibration_catphan/instance_1/output/extended_calibration_evaluations.csv`

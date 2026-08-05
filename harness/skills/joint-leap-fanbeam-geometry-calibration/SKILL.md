---
name: joint-leap-fanbeam-geometry-calibration
description: Use when the input provides `sinogram.npy`, `reference_image.npy`, and a nominal LEAP/leaptorch FBP script whose fan-beam geometry must be calibrated.
provenance: claude-code
target_arch: ale-claw-base
donor_arch: claude-code
signal_type: crossarch
task_class: health_medicine/ct_geometry_calibration_catphan
---
1. **Read and reproduce the nominal pipeline.** Inspect `<input>/reconstruct.py` for detector dimensions, angle construction, detector type, volume dimensions, FBP call, scan direction, and all fixed geometry values. Run the unchanged baseline with:
   ```bash
   software/python <input>/reconstruct.py <input>/sinogram.npy --output <work>/baseline.npy
   ```
   Compute the baseline exactly as:
   ```python
   mse = np.mean((ref.astype(np.float64) - rec.astype(np.float64))**2)
   score = structural_similarity(ref, rec, data_range=float(ref.max() - ref.min()))
   ```

2. **Create an in-process reconstruction function.** Load the sinogram and reference once, then define `reconstruct(params)` that creates/configures a LEAP/leaptorch `Projector`, constructs `n_view` angles from `phi0`, `scan_arc`, and direction, sets fan-beam geometry, sets detector offset and `tau`, configures the volume with `dx`/`dy`, runs FBP, and returns a `512x512` NumPy array. Recreate the projector for each candidate so no previous geometry state leaks between evaluations. Catch LEAP geometry errors and return a large finite penalty.

3. **Diagnose which parameter groups need a broad search.** Forward-project the reference under the nominal geometry and compare it with the measured sinogram. A residual dominated by its mean over views indicates detector-coordinate errors such as pitch or offset; a residual changing systematically with view suggests `tau`, `phi0`, scan direction, or scan-arc error. Use this only to choose search ranges—not as the final objective—because SAD, SDD, and detector pitch can form nearly flat equivalent-sampling valleys.

4. **Locate a coupled basin.** Profile individual variables around their nominal values, then evaluate small grids for `du × detector_offset`, `dx × du`, and `phi0 × scan_arc`. Treat positive and negative scan directions as separate branches. Retain several best candidates rather than only the best one-dimensional result. Use an objective such as:
   ```python
   loss = (1.0 - score) + mse / max(float(np.var(ref)), np.finfo(float).eps)
   ```
   Optionally compare high-pass correlation, `corr(ref-gaussian_filter(ref,s), rec-gaussian_filter(rec,s))`, to distinguish coarse structural agreement from sub-pixel geometric alignment.

5. **Jointly refine all relevant dimensions.** Start `scipy.optimize.differential_evolution` from physically valid bounds when the basin is unknown, or refine retained grid candidates using `scipy.optimize.minimize(..., method="Nelder-Mead")`. Optimize `[SAD, SDD, detector_offset, du, tau, dx, phi0, scan_arc]`, tying `dy=dx` unless the source script indicates anisotropy. Do not freeze `phi0` or scan arc merely because the input claims a nominal uniform full rotation; sub-view angular errors can dominate SSIM after scale and offset are corrected.

6. **Emit the required artifacts.** Reconstruct once with the selected parameter vector, cast to `float32`, and save it as `<output>/reconstructed_calibrated.npy`. Save all effective geometry values—including angle convention, detector pitch, voxel spacing, offset, and `tau`—to `<output>/geometry_calibrated.json` using plain JSON numbers.

7. **Numeric acceptance check.** Compute `skimage.metrics.structural_similarity` and unnormalized `mean((ref - recon)**2)` on the saved reconstruction. The candidate is acceptable only if `SSIM >= 0.95 and unnormalized MSE <= 4e-6`; otherwise continue the coupled detector/angular optimization.

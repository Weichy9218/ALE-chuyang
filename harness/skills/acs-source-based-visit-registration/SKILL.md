---
name: acs-source-based-visit-registration
description: Use when implementing `reduce_visit.py --input <visit_root_or_parent_input_dir> --output <output_dir>` for ACS/WFC visits containing `visit_asn.csv`, FLT FITS images, DQ masks, and calibration/reference metadata.
provenance: claude-code
target_arch: argus
donor_arch: claude-code
signal_type: crossarch
task_class: physical_sciences/hst_acs_wfc_visit_reduction
---
1. **Discover visits without assuming a fixed directory name.** If `<input>/visit_asn.csv` exists, process `<input>` as one visit. Otherwise process each immediate child containing `visit_asn.csv`. Derive exposure paths, exposure times, nominal shifts, and filters from the association table.

2. **Use the supplied runtime.** Invoke probes and the final program through `<python_wrapper>`. Load each FLT array using `astropy.io.fits`, and obtain its dimensions from the array rather than fixing a mosaic size.

3. **Calibrate before measuring positions.** For each exposure, compute a calibrated count-rate image equivalent to `(raw_electrons - bias_electrons - dark_electrons_per_s * exptime_s) / flat / exptime_s`. Read the corresponding DQ CSV and invalidate pixels where `(dq & 16) != 0` or `(dq & 4096) != 0`. Also reject non-finite or non-positive flat values.

4. **Build measured source lists.** Estimate the background and noise robustly, for example with `sigma = 1.4826 * median(abs(image - median(image)))`. Find local maxima above a configurable `5 sigma` threshold, exclude masked pixels, and calculate flux-weighted subpixel centroids in a small odd-sized window. Do not create detections merely by copying every reference-catalog entry.

5. **Solve exposure translations.** Choose a well-populated exposure as the reference. For every other exposure, predict correspondence using the nominal association shift, match centroids within a configurable radius, and calculate `dx = x_observed - x_reference` and `dy = y_observed - y_reference`. Fit the translation with medians and iteratively reject residuals beyond `3` robust sigmas. Record the measured shift, residual RMS, and surviving match count.

6. **Apply the measured sign correctly.** Under `observed = reference + fitted_shift`, the value at mosaic coordinate `(x, y)` is sampled from exposure coordinate `(x + dx, y + dy)`. Use a subpixel interpolator such as `scipy.ndimage.map_coordinates` or an equivalent drizzle-style weighted deposition. Propagate a weight map so masked and out-of-bounds samples contribute zero weight.

7. **Establish the WCS from actual matches.** Build a TAN WCS with `astropy.wcs.WCS` from the supplied `ra0_deg`, `dec0_deg`, and `pixel_scale_arcsec`, placing the tangent point at the image center derived from its dimensions. Evaluate plausible x/y handedness conventions by projecting reference coordinates and matching them to measured mosaic centroids; select the convention with the lowest robust residual rather than hard-coding a sign.

8. **Extract final photometry from the mosaic.** Detect sources on the coadd, measure background-subtracted aperture flux in electrons per second, and compute `mag_ab = ab_zeropoint - 2.5 * log10(flux_e_s)` only for positive finite flux. Populate sky coordinates through the fitted WCS and preserve the required catalog columns and five output filenames.

9. **Numeric acceptance check.** Require exactly one alignment row for every association-table exposure, at least `3` retained centroid matches per solved exposure, and robust registration RMS `< 0.5 pixel`. Also require the sky-match RMS converted to pixels to be `< 0.5 pixel`; otherwise report the visit as failing alignment rather than presenting nominal shifts as a measured solution.

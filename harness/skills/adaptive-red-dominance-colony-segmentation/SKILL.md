---
name: adaptive-red-dominance-colony-segmentation
description: Use when the input interface provides an RGB yeast-plate image, a plate-region mask, and requires red-colony centroids while excluding white dots and colored plate artifacts.
provenance: claude-code
target_arch: argus
donor_arch: claude-code
signal_type: crossarch
task_class: life_sciences/yeast_colony_detection
---
1. **Select the scientific Python runtime.** Inspect `<cellprofiler-entry>` to locate its installation root, then use `<cellprofiler-root>/bin/python3`. Check it with:
   ```bash
   <cp-python> -c "import numpy, scipy.ndimage, skimage.measure, skimage.morphology, PIL"
   ```

2. **Load and normalize the inputs.** Read `<image>` as RGB float data and `<mask>` as a binary plate region. Resolve mask polarity by selecting the large connected region containing the image center, then fill internal mask holes. Do not modify either input file.

3. **Compute strict red dominance.** For each pixel calculate:
   ```python
   D = R - np.maximum(G, B)
   ```
   This is preferable to `R - (G+B)/2`: a yellow reflection can score positively under the latter because blue is low, whereas `R - max(G,B)` requires red to exceed both competing channels.

4. **Derive an image-specific threshold.** From `D` inside the plate mask compute:
   ```python
   center = np.median(D_plate)
   sigma = 1.4826 * np.median(np.abs(D_plate - center))
   threshold = max(0, center + 8 * sigma)
   foreground = plate_mask & (D > threshold)
   ```
   Median/MAD calibration is robust when colonies occupy a minority of the plate. The zero floor preserves the physical requirement `R > G` and `R > B`.

5. **Form colony objects.** Apply light binary closing and hole filling, then remove components below a recorded `<minimum-area-px>` chosen to exclude isolated pixel/JPEG noise without removing the smallest spatially coherent red spot. Label with 8-connectivity. Keep components touching the plate boundary when their centroid lies in the original plate mask. Apply distance-transform watershed only to components that are both substantially larger than the ordinary component-size distribution and low in solidity.

6. **Measure and export.** For each retained component, use `skimage.measure.regionprops`; map centroid `(row, column)` to `Location_Center_Y = row` and `Location_Center_X = column`. Write one CSV row per object to `<output>/measurements/RedColonies.csv`, including numeric `Location_Center_X`, `Location_Center_Y`, and preferably sequential `ObjectNumber`. Write `<output>/answer.json` using exactly `{"colony_count": <integer>}`. Save the complete parameterized script under `<output>` for reproducibility.

7. **Numeric domain acceptance check.** Every accepted object's core median red-dominance score must be at least `8σ` above the robust agar center, where `σ = 1.4826 * MAD(D_plate)`, and accepted foreground pixels must satisfy both `R > G` and `R > B`. This check directly tests exclusion of white, yellow, and blue structures without sacrificing valid colonies merely because they lie near the mask edge.

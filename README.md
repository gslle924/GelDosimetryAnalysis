MRGelDosimetry is a 3D Slicer extension for MR-based gel dosimetry analysis. 
Building on the existing optical CT gel dosimetry workflow, this extension adapts the pipeline for MR imaging and 
provides a streamlined workflow for ΔR1 map generation, image registration, dose calibration, and dose comparison.

Both workflows are available in this repository:
- MR workflow: `GelDosimetryAnalysis.py` and `GelDosimetryAnalysisLogic.py` (active by default)
- Optical CT workflow: `GelDosimetryAnalysis_oCT.py` and `GelDosimetryAnalysisLogic_oCT.py`

To switch to the optical CT workflow, 
remove the `_oCT` suffix from `GelDosimetryAnalysis_oCT.py` and `GelDosimetryAnalysisLogic_oCT.py`, 
and rename the MR files to avoid conflicts (e.g. add `_MR` suffix). 
Only one set of `GelDosimetryAnalysis.py` and `GelDosimetryAnalysisLogic.py` files should be active at a time.

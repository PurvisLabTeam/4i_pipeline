# 4i_pipeline
Notebooks and environments for running the 4i pipeline

# Environment Usage
Use GPU_Segment_4i for notebooks 00, 01, 02, 04, and 06

Use Masking_4i for notebooks 03 and 05

The environment split avoids conflicts between Napari and Cellpose

# Expected outputs
The pipeline takes images from the Purvis lab Photon microscope system and outputs .csv. and .pkl files for each well. These contain feature data for each round of imaging and are used for downstream analysis.

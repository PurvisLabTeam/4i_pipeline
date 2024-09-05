# 4i_pipeline
Notebooks and environments for running the 4i pipeline

# Environment Usage
Use GPU_Segment_4i for notebooks 00, 01, 02, 04, and 06

Use Masking_4i for notebooks 03 and 05

The environment split avoids conflicts between Napari and Cellpose

# Expected outputs
The pipeline takes images from the Purvis lab Photon microscope system and outputs .csv. and .pkl files for each well. These contain feature data for each round of imaging and are used for downstream analysis.

# Notebook Descriptions
Notebook 00 prepares images for processing by ensuring uniform size and extracting the channel to be used for alignment. 

Notebook 01 performs the segmentation using either the GPU or CPU

Notebook 02 using the segmentation masks to determine the transformation required to align all channels of the images

Notebook 03 is only used if the automatic transformations are incorrect, usually as a result of underlying issues with the data

Notebook 04 applies the transformation matrixes generated in notebook 02 or 03 to all channels of the images, generating a set of aligned tiffs

Notebook 05 uses a Napari interface to mask out debris and other artifacts ensuring the quality of the data

Notebook 06 calculates the properties of individual cells and outputs a .csv and a .pkl file for each well of the 96 well plate imaged.

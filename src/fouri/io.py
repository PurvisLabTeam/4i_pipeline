"""File helpers shared by the pipeline notebooks."""

import os

import nd2
import numpy as np
from tifffile import imread


def make_dir(path, what="output"):
    """Create ``path`` (and parents) if needed and say whether it was created."""
    if os.path.isdir(path):
        print(f"Directory for {what} exists: {path}")
    else:
        os.makedirs(path)
        print(f"Directory for {what} created: {path}")


def nd2_info(path):
    """(sizes, channel names) of an ND2 file, closing the file afterwards."""
    with nd2.ND2File(path) as f:
        sizes = dict(f.sizes)
        channels = [c.channel.name for c in f.metadata.channels]
    return sizes, channels


def read_nd2_channel(path, channel):
    """Read one channel of an ND2 file into memory and close the file."""
    with nd2.ND2File(path) as f:
        return np.asarray(f.to_dask()[channel, :, :].compute())


def read_labels(path_labels, well, indices=None):
    """Stack of a well's label images (sorted by file name).

    ``indices`` picks specific images, e.g. [anchor, moving] in notebook 03.
    """
    names = sorted(x for x in os.listdir(os.path.join(path_labels, well)) if "tif" in x)
    if indices is not None:
        names = [names[int(i)] for i in indices]
    return np.array([imread(os.path.join(path_labels, well, n)) for n in names])

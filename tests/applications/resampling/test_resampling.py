#!/usr/bin/env python
# coding: utf8
#
# Copyright (c) 2020 Centre National d'Etudes Spatiales (CNES).
#
# This file is part of CARS
# (see https://github.com/CNES/cars).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
Test module for cars/stereo.py
Important : Uses conftest.py for shared pytest fixtures
"""

import os
import pickle
import tempfile

# Third party imports
import numpy as np
import pytest
import xarray as xr

from cars.applications.application import Application

# CARS imports
from cars.applications.resampling import bicubic_resampling, resampling_tools
from cars.conf import input_parameters as in_params
from cars.core import constants as cst
from cars.core import tiling
from cars.orchestrator import orchestrator
from cars.pipelines.parameters import sensor_inputs
from cars.pipelines.parameters import sensor_inputs_constants as sens_cst

# CARS Tests imports
from ...helpers import (
    absolute_data_path,
    assert_same_datasets,
    generate_input_json,
    get_geometry_plugin,
    temporary_dir,
)


@pytest.mark.unit_tests
def test_resample_image():
    """
    Test resample image method
    """
    region = [387, 180, 564, 340]

    img = absolute_data_path("input/phr_ventoux/left_image.tif")
    nodata = 0
    grid = absolute_data_path("input/stereo_input/left_epipolar_grid.tif")
    epipolar_size_x = 612
    epipolar_size_y = 612

    test_dataset = resampling_tools.resample_image(
        img,
        grid,
        [epipolar_size_x, epipolar_size_y],
        region=region,
        nodata=nodata,
    )

    # Uncomment to update baseline
    # test_dataset.to_netcdf(absolute_data_path("ref_output/data1_ref_left.nc"))

    # For convenience we use same reference as test_epipolar_rectify_images_1
    ref_dataset = xr.open_dataset(
        absolute_data_path("ref_output/data1_ref_left.nc")
    )

    # We need to remove attributes that are not generated by resample_image
    # method
    ref_dataset.attrs.pop(cst.ROI, None)
    ref_dataset.attrs.pop(cst.EPI_MARGINS, None)
    ref_dataset.attrs.pop(cst.EPI_DISP_MIN, None)
    ref_dataset.attrs.pop(cst.EPI_DISP_MAX, None)
    ref_dataset.attrs.pop(cst.ROI_WITH_MARGINS, None)
    ref_dataset.attrs.pop(cst.ROI_WITH_MARGINS, None)

    assert_same_datasets(test_dataset, ref_dataset)


@pytest.mark.unit_tests
def test_resample_image_tiles():
    """
    Test resample image method, tile same as full cropped
    """
    region = [387, 180, 564, 340]

    img = absolute_data_path(
        "input/phr_ventoux/left_image_modified_transform.tif"
    )
    nodata = 0
    grid = absolute_data_path("input/stereo_input/left_epipolar_grid.tif")
    epipolar_size_x = 612
    epipolar_size_y = 612

    full_dataset = resampling_tools.resample_image(
        img,
        grid,
        [epipolar_size_x, epipolar_size_y],
        nodata=nodata,
    )

    tiled_dataset = resampling_tools.resample_image(
        img,
        grid,
        [epipolar_size_x, epipolar_size_y],
        region=region,
        nodata=nodata,
    )

    offset = 40

    full_arr = full_dataset["im"].values[
        region[1] + offset : region[3] - offset,
        region[0] + offset : region[2] - offset,
    ]
    tiled_arr = tiled_dataset["im"].values[offset:-offset, offset:-offset]

    np.testing.assert_equal(full_arr, tiled_arr)


@pytest.mark.unit_tests
def test_epipolar_rectify_images_1(
    images_and_grids_conf,
    color1_conf,  # pylint: disable=redefined-outer-name
    epipolar_sizes_conf,  # pylint: disable=redefined-outer-name
    epipolar_origins_spacings_conf,  # pylint: disable=redefined-outer-name
    no_data_conf,
):  # pylint: disable=redefined-outer-name
    """
    Test epipolar_rectify_image on ventoux dataset (epipolar geometry)
    with nodata and color
    """
    configuration = images_and_grids_conf
    configuration["input"].update(color1_conf["input"])
    configuration["input"].update(no_data_conf["input"])
    configuration["preprocessing"]["output"].update(
        epipolar_sizes_conf["preprocessing"]["output"]
    )
    configuration["preprocessing"]["output"].update(
        epipolar_origins_spacings_conf["preprocessing"]["output"]
    )

    region = [420, 200, 530, 320]
    col = np.arange(4)
    margin = xr.Dataset(
        {"left_margin": (["col"], np.array([33, 20, 34, 20]))},
        coords={"col": col},
    )
    margin["right_margin"] = xr.DataArray(
        np.array([33, 20, 34, 20]), dims=["col"]
    )

    margin.attrs[cst.EPI_DISP_MIN] = -13
    margin.attrs[cst.EPI_DISP_MAX] = 14

    # Rectify images
    # retrieves some data
    epipolar_size_x = configuration["preprocessing"]["output"][
        "epipolar_size_x"
    ]
    epipolar_size_y = configuration["preprocessing"]["output"][
        "epipolar_size_y"
    ]
    img1 = configuration["input"][in_params.IMG1_TAG]
    img2 = configuration["input"][in_params.IMG2_TAG]
    color1 = configuration["input"].get(in_params.COLOR1_TAG, None)
    grid1 = configuration["preprocessing"]["output"]["left_epipolar_grid"]
    grid2 = configuration["preprocessing"]["output"]["right_epipolar_grid"]
    nodata1 = configuration["input"].get(in_params.NODATA1_TAG, None)
    nodata2 = configuration["input"].get(in_params.NODATA2_TAG, None)
    mask1 = configuration["input"].get(in_params.MASK1_TAG, None)
    mask2 = configuration["input"].get(in_params.MASK2_TAG, None)
    classif1 = configuration["input"].get(in_params.CLASSIFICATION1_TAG, None)
    classif2 = configuration["input"].get(in_params.CLASSIFICATION2_TAG, None)

    (
        left,
        right,
        clr,
        classif1,
        classif2,
    ) = resampling_tools.epipolar_rectify_images(
        img1,
        img2,
        grid1,
        grid2,
        region,
        margin,
        epipolar_size_x,
        epipolar_size_y,
        color1=color1,
        mask1=mask1,
        mask2=mask2,
        classif1=classif1,
        classif2=classif2,
        nodata1=nodata1,
        nodata2=nodata2,
        add_color=True,
    )

    print("\nleft dataset: {}".format(left))
    print("right dataset: {}".format(right))
    print("clr dataset: {}".format(clr))

    # Uncomment to update baseline
    # left.to_netcdf(absolute_data_path("ref_output/data1_ref_left.nc"))

    left_ref = xr.open_dataset(
        absolute_data_path("ref_output/data1_ref_left.nc")
    )
    assert_same_datasets(left, left_ref)

    # Uncomment to update baseline
    # right.to_netcdf(absolute_data_path("ref_output/data1_ref_right.nc"))

    right_ref = xr.open_dataset(
        absolute_data_path("ref_output/data1_ref_right.nc")
    )
    assert_same_datasets(right, right_ref)

    # Uncomment to update baseline
    # with open(absolute_data_path("ref_output/data1_ref_color"), "wb") as file:
    #     pickle.dump(clr, file)

    with open(
        absolute_data_path("ref_output/data1_ref_color"),
        "rb",
    ) as file2:
        # load pickle data
        clr_ref = pickle.load(file2)
        assert_same_datasets(clr, clr_ref)


@pytest.mark.unit_tests
def test_epipolar_rectify_images_3(
    images_and_grids_conf,  # pylint: disable=redefined-outer-name
    color_pxs_conf,  # pylint: disable=redefined-outer-name
    epipolar_sizes_conf,  # pylint: disable=redefined-outer-name
    epipolar_origins_spacings_conf,  # pylint: disable=redefined-outer-name
    no_data_conf,
):  # pylint: disable=redefined-outer-name
    """
    Test epipolar_rectify_image on ventoux dataset (epipolar geometry)
    with nodata and color as a p+xs fusion
    """
    configuration = images_and_grids_conf
    configuration["input"].update(color_pxs_conf["input"])
    configuration["input"].update(no_data_conf["input"])
    configuration["preprocessing"]["output"].update(
        epipolar_sizes_conf["preprocessing"]["output"]
    )
    configuration["preprocessing"]["output"].update(
        epipolar_origins_spacings_conf["preprocessing"]["output"]
    )

    region = [420, 200, 530, 320]
    col = np.arange(4)
    margin = xr.Dataset(
        {"left_margin": (["col"], np.array([33, 20, 34, 20]))},
        coords={"col": col},
    )
    margin["right_margin"] = xr.DataArray(
        np.array([33, 20, 34, 20]), dims=["col"]
    )

    margin.attrs[cst.EPI_DISP_MIN] = -13
    margin.attrs[cst.EPI_DISP_MAX] = 14

    # Rectify images
    # retrieves some data
    epipolar_size_x = configuration["preprocessing"]["output"][
        "epipolar_size_x"
    ]
    epipolar_size_y = configuration["preprocessing"]["output"][
        "epipolar_size_y"
    ]
    img1 = configuration["input"][in_params.IMG1_TAG]
    img2 = configuration["input"][in_params.IMG2_TAG]
    color1 = configuration["input"].get(in_params.COLOR1_TAG, None)
    grid1 = configuration["preprocessing"]["output"]["left_epipolar_grid"]
    grid2 = configuration["preprocessing"]["output"]["right_epipolar_grid"]
    nodata1 = configuration["input"].get(in_params.NODATA1_TAG, None)
    nodata2 = configuration["input"].get(in_params.NODATA2_TAG, None)
    mask1 = configuration["input"].get(in_params.MASK1_TAG, None)
    mask2 = configuration["input"].get(in_params.MASK2_TAG, None)
    classif1 = configuration["input"].get(in_params.CLASSIFICATION1_TAG, None)
    classif2 = configuration["input"].get(in_params.CLASSIFICATION2_TAG, None)
    (
        left,
        right,
        clr,
        class1,
        class2,
    ) = resampling_tools.epipolar_rectify_images(
        img1,
        img2,
        grid1,
        grid2,
        region,
        margin,
        epipolar_size_x,
        epipolar_size_y,
        color1=color1,
        mask1=mask1,
        mask2=mask2,
        classif1=classif1,
        classif2=classif2,
        nodata1=nodata1,
        nodata2=nodata2,
        add_color=True,
    )

    print("\nleft dataset: {}".format(left))
    print("right dataset: {}".format(right))
    print("clr dataset: {}".format(clr))

    left_ref = xr.open_dataset(
        absolute_data_path("ref_output/data1_ref_left.nc")
    )
    assert_same_datasets(left, left_ref)

    right_ref = xr.open_dataset(
        absolute_data_path("ref_output/data1_ref_right.nc")
    )
    assert_same_datasets(right, right_ref)

    # Uncomment to update baseline
    # with open(absolute_data_path(os.path.join(
    #           "ref_output","data3_ref_color_4bands"
    #      )), "wb") as file:
    #     pickle.dump(clr, file)

    with open(
        absolute_data_path(
            os.path.join("ref_output", "data3_ref_color_4bands")
        ),
        "rb",
    ) as file2:
        # load pickle data
        clr_ref = pickle.load(file2)
        assert_same_datasets(clr, clr_ref)

    assert class1 is None
    assert class2 is None


@pytest.mark.unit_tests
def test_check_tiles_in_sensor():
    """
    Test tile dumping
    """

    with tempfile.TemporaryDirectory(dir=temporary_dir()) as directory:
        input_json = absolute_data_path("input/phr_ventoux/input.json")

        _, input_data = generate_input_json(
            input_json,
            directory,
            "sensors_to_dense_dsm",
            "local_dask",
            orchestrator_parameters={
                "walltime": "00:10:00",
                "nb_workers": 4,
                "max_ram_per_worker": 1000,
            },
        )

        inputs = input_data["inputs"]
        list_sensor_pairs = sensor_inputs.generate_inputs(
            inputs, get_geometry_plugin()
        )

        sensor_image_left = list_sensor_pairs[0][1]

        sensor_image_right = list_sensor_pairs[0][2]

        # Generate grids
        geometry_plugin = get_geometry_plugin(
            dem=inputs[sens_cst.INITIAL_ELEVATION][sens_cst.DEM_PATH],
            default_alt=sens_cst.CARS_DEFAULT_ALT,
        )

        with orchestrator.Orchestrator(
            orchestrator_conf={"mode": "sequential"}
        ) as cars_orchestrator:
            epipolar_grid_generation_application = Application(
                "grid_generation"
            )
            (
                grid_left,
                grid_right,
            ) = epipolar_grid_generation_application.run(
                sensor_image_left,
                sensor_image_right,
                geometry_plugin,
                orchestrator=cars_orchestrator,
                pair_folder=directory,
                pair_key="one_two",
            )

        opt_epipolar_tile_size = 10

        # generate epipolar image tiling grid
        epi_tilling_grid = tiling.generate_tiling_grid(
            0,
            0,
            grid_left.attributes["epipolar_size_y"],
            grid_left.attributes["epipolar_size_x"],
            opt_epipolar_tile_size,
            opt_epipolar_tile_size,
        )

        # Check if tiles are in sensors
        (
            in_sensor_left_array,
            in_sensor_right_array,
        ) = bicubic_resampling.check_tiles_in_sensor(
            sensor_image_left,
            sensor_image_right,
            epi_tilling_grid,
            grid_left,
            grid_right,
        )

        # Assert number of tiles used

        # 3059 tiles used on 3844
        assert np.sum(in_sensor_left_array) == 3059
        # 1426 tiles used on 3844
        assert np.sum(in_sensor_right_array) == 1426

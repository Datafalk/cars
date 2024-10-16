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
# pylint: disable=too-many-lines
"""
this module contains the LineOfSightIntersection application class.
"""

# Standard imports
import logging
import os
from typing import Dict, Tuple

# Third party imports
import numpy as np
import pandas
import xarray as xr
from json_checker import Checker

# CARS imports
import cars.orchestrator.orchestrator as ocht
from cars.applications import application_constants
from cars.applications.grid_generation import grids
from cars.applications.triangulation import (
    triangulation_constants,
    triangulation_tools,
)
from cars.applications.triangulation.triangulation import Triangulation
from cars.conf import mask_cst
from cars.core import constants as cst
from cars.core import inputs, projection, tiling
from cars.core.utils import safe_makedirs
from cars.data_structures import cars_dataset
from cars.pipelines.parameters import sensor_inputs_constants as sens_cst


class LineOfSightIntersection(
    Triangulation, short_name="line_of_sight_intersection"
):
    """
    Triangulation
    """

    def __init__(self, conf=None):
        """
        Init function of Triangulation

        :param conf: configuration for triangulation
        :return: an application_to_use object
        """

        super().__init__(conf=conf)
        # check conf
        self.used_method = self.used_config["method"]
        self.snap_to_img1 = self.used_config["snap_to_img1"]
        # Saving files
        self.save_intermediate_data = self.used_config["save_intermediate_data"]

        # global value for left image to check if snap_to_img1 can
        # be applied : Need than same application object is run
        # for all pairs
        self.ref_left_img = None

        # Init orchestrator
        self.orchestrator = None

    def check_conf(self, conf):
        """
        Check configuration

        :param conf: configuration to check
        :type conf: dict

        :return: overloaded configuration
        :rtype: dict

        """

        # init conf
        if conf is not None:
            overloaded_conf = conf.copy()
        else:
            conf = {}
            overloaded_conf = {}

        # Overload conf
        overloaded_conf["method"] = conf.get(
            "method", "line_of_sight_intersection"
        )
        overloaded_conf["snap_to_img1"] = conf.get("snap_to_img1", False)

        # Saving files
        overloaded_conf["save_intermediate_data"] = conf.get(
            "save_intermediate_data", False
        )

        triangulation_schema = {
            "method": str,
            "snap_to_img1": bool,
            "save_intermediate_data": bool,
        }

        # Check conf
        checker = Checker(triangulation_schema)
        checker.validate(overloaded_conf)

        return overloaded_conf

    def save_triangulation_output(
        self,
        epipolar_points_cloud,
        sensor_image_left,
        output_dir,
        dump_dir=None,
        intervals=None,
        save_output_color=True,
        save_output_classification=False,
        save_output_mask=False,
        save_output_filling=False,
        save_output_performance_map=False,
    ):
        """
        Save the triangulation output. The different TIFs composing the depth
        map are written to the output directory. Auxiliary products can be
        requested or not using the parameters. A dump directory can also be
        provided to write any additionnal files that have not been written
        to the output directory (because they are not part of the depth map
        definition, or because they have not been requested)

        :param epipolar_points_cloud: tiled epipolar left image
        :type epipolar_points_cloud: CarsDataset
        :param sensor_image_left: tiled sensor left image
            Dict Must contain keys : "image", "color", "geomodel",
            "no_data", "mask". Paths must be absolutes
        :type sensor_image_left: CarsDataset
        :param output_dir: directory to write triangulation output depth
                map.
        :type output_dir: None or str
        :param dump_dir: folder used as dump directory for current pair, None to
                deactivate intermediate data writing
        :type dump_dir: str
        :param intervals: Either None or a List of 2 intervals indicators
        :type intervals: None or [str, str]
        :param save_output_color: Save color depth map in output_dir
        :type save_output_color: bool
        :param save_output_classification: Save classification depth map in
                output_dir
        :type save_output_classification: bool
        :param save_output_mask: Save mask depth map in output_dir
        :type save_output_mask: bool
        :param save_output_filling: Save filling depth map in output_dir
        :type save_output_filling: bool
        :param save_output_performance_map: Save performance map in output_dir
        :type save_output_performance_map: bool
        """

        if dump_dir:
            safe_makedirs(dump_dir)

        # Propagate color type in output file
        color_type = None
        if sens_cst.INPUT_COLOR in sensor_image_left:
            color_type = inputs.rasterio_get_image_type(
                sensor_image_left[sens_cst.INPUT_COLOR]
            )
        else:
            color_type = inputs.rasterio_get_image_type(
                sensor_image_left[sens_cst.INPUT_IMG]
            )

        if output_dir is None:
            output_dir = dump_dir
        if output_dir:
            self.orchestrator.add_to_save_lists(
                os.path.join(output_dir, "X.tif"),
                cst.X,
                epipolar_points_cloud,
                cars_ds_name="depth_map_x",
                dtype=np.float64,
            )

            self.orchestrator.add_to_save_lists(
                os.path.join(output_dir, "Y.tif"),
                cst.Y,
                epipolar_points_cloud,
                cars_ds_name="depth_map_y",
                dtype=np.float64,
            )

            self.orchestrator.add_to_save_lists(
                os.path.join(output_dir, "Z.tif"),
                cst.Z,
                epipolar_points_cloud,
                cars_ds_name="depth_map_z",
                dtype=np.float64,
            )

        if save_output_color or dump_dir:
            color_output_dir = output_dir if save_output_color else dump_dir
            self.orchestrator.add_to_save_lists(
                os.path.join(color_output_dir, "color.tif"),
                cst.EPI_COLOR,
                epipolar_points_cloud,
                cars_ds_name="depth_map_color",
                dtype=color_type,
            )

        if save_output_mask or dump_dir:
            mask_output_dir = output_dir if save_output_mask else dump_dir
            self.orchestrator.add_to_save_lists(
                os.path.join(mask_output_dir, "mask.tif"),
                cst.EPI_MSK,
                epipolar_points_cloud,
                cars_ds_name="depth_map_msk",
                nodata=mask_cst.NO_DATA_IN_EPIPOLAR_RECTIFICATION,
                optional_data=True,
                dtype=np.uint8,
            )

        if save_output_performance_map or dump_dir:
            map_output_dir = (
                output_dir if save_output_performance_map else dump_dir
            )
            self.orchestrator.add_to_save_lists(
                os.path.join(map_output_dir, "performance_map.tif"),
                cst.EPI_PERFORMANCE_MAP,
                epipolar_points_cloud,
                cars_ds_name="depth_map_performance_map",
                optional_data=True,
                dtype=np.float64,
            )

        if save_output_classification or dump_dir:
            classif_output_dir = (
                output_dir if save_output_classification else dump_dir
            )
            self.orchestrator.add_to_save_lists(
                os.path.join(classif_output_dir, "classification.tif"),
                cst.EPI_CLASSIFICATION,
                epipolar_points_cloud,
                cars_ds_name="depth_map_classification",
                optional_data=True,
                dtype=np.uint8,
            )

        if save_output_filling or dump_dir:
            filling_output_dir = output_dir if save_output_filling else dump_dir
            self.orchestrator.add_to_save_lists(
                os.path.join(filling_output_dir, "filling.tif"),
                cst.EPI_FILLING,
                epipolar_points_cloud,
                cars_ds_name="depth_map_filling",
                optional_data=True,
                dtype=np.uint8,
                nodata=255,
            )

        if dump_dir and intervals is not None:
            self.orchestrator.add_to_save_lists(
                os.path.join(dump_dir, "Z_inf.tif"),
                cst.Z_INF,
                epipolar_points_cloud,
                cars_ds_name="depth_map_z_inf",
            )
            self.orchestrator.add_to_save_lists(
                os.path.join(dump_dir, "Z_sup.tif"),
                cst.Z_SUP,
                epipolar_points_cloud,
                cars_ds_name="depth_map_z_sup",
            )

        if dump_dir:
            self.orchestrator.add_to_save_lists(
                os.path.join(dump_dir, "corr_mask.tif"),
                cst.POINTS_CLOUD_CORR_MSK,
                epipolar_points_cloud,
                cars_ds_name="depth_map_corr_msk",
                optional_data=True,
            )

    def run(  # noqa: C901
        self,
        sensor_image_left,
        sensor_image_right,
        epipolar_image,
        grid_left,
        grid_right,
        epipolar_disparity_map,
        epsg,
        geometry_plugin,
        denoising_overload_fun=None,
        source_pc_names=None,
        orchestrator=None,
        pair_dump_dir=None,
        pair_key="PAIR_0",
        uncorrected_grid_right=None,
        geoid_path=None,
        cloud_id=None,
        intervals=None,
        pair_output_dir=None,
        save_output_color=False,
        save_output_classification=False,
        save_output_mask=False,
        save_output_filling=False,
        save_output_performance_map=False,
    ):
        """
        Run Triangulation application.

        Created left and right CarsDataset filled with xarray.Dataset,
        corresponding to 3D points clouds, stored on epipolar geometry grid.

        :param sensor_image_left: tiled sensor left image
            Dict Must contain keys : "image", "color", "geomodel",
            "no_data", "mask". Paths must be absolutes
        :type sensor_image_left: CarsDataset
        :param sensor_image_right: tiled sensor right image
            Dict Must contain keys : "image", "color", "geomodel",
            "no_data", "mask". Paths must be absolutes
        :type sensor_image_right: CarsDataset
        :param epipolar_image: tiled epipolar left image
        :type epipolar_image: CarsDataset
        :param grid_left: left epipolar grid. Grid CarsDataset contains :

            - A single tile stored in [0,0], containing a (N, M, 2) shape \
                array in xarray Dataset
            - Attributes containing: "grid_spacing", "grid_origin",\
                "epipolar_size_x", epipolar_size_y", "epipolar_origin_x",\
                "epipolar_origin_y","epipolar_spacing_x",\
                "epipolar_spacing", "disp_to_alt_ratio",\
        :type grid_left: CarsDataset
        :param grid_right: right epipolar grid. Grid CarsDataset contains :

            - A single tile stored in [0,0], containing a (N, M, 2) shape
                array in xarray Dataset
            - Attributes containing: "grid_spacing", "grid_origin",
                "epipolar_size_x", epipolar_size_y", "epipolar_origin_x",
                "epipolar_origin_y","epipolar_spacing_x",
                "epipolar_spacing", "disp_to_alt_ratio",
        :type grid_right: CarsDataset
        :param epipolar_disparity_map: tiled left disparity map or \
            sparse matches:

            - if CarsDataset is instance of "arrays", CarsDataset contains:

                - N x M Delayed tiles \
                    Each tile will be a future xarray Dataset containing:

                    - data with keys : "disp", "disp_msk"
                    - attrs with keys: profile, window, overlaps
                - attributes containing:"largest_epipolar_region"\
                  "opt_epipolar_tile_size"

            - if CarsDataset is instance of "points", CarsDataset contains:

                - N x M Delayed tiles \
                    Each tile will be a future pandas DataFrame containing:

                    - data : (L, 4) shape matches
                - attributes containing:"disp_lower_bound","disp_upper_bound",\
                    "elevation_delta_lower_bound","elevation_delta_upper_bound"

        :type epipolar_disparity_map: CarsDataset
        :param denoising_overload_fun: function to overload dataset
        :type denoising_overload_fun: fun
        :param source_pc_names: source pc names
        :type source_pc_names: list[str]
        :param orchestrator: orchestrator used
        :param pair_dump_dir: folder used as dump directory for current pair
        :type pair_dump_dir: str
        :param pair_key: pair key id
        :type pair_key: str
        :param uncorrected_grid_right: not corrected right epipolar grid
                used if self.snap_to_img1
        :type uncorrected_grid_right: CarsDataset
        :param geoid_path: geoid path
        :type geoid_path: str
        :param intervals: Either None or a List of 2 intervals indicators
        :type intervals: None or [str, str]
        :param pair_output_dir: directory to write triangulation output depth
                map.
        :type pair_output_dir: None or str
        :param save_output_color: Save color depth map in pair_output_dir
        :type save_output_color: bool
        :param save_output_classification: Save classification depth map in
                pair_output_dir
        :type save_output_classification: bool
        :param save_output_mask: Save mask depth map in pair_output_dir
        :type save_output_mask: bool
        :param save_output_filling: Save filling depth map in pair_output_dir
        :type save_output_filling: bool
        :param save_output_performance_map: Save performance map in
                pair_output_dir
        :type save_output_performance_map: bool

        :return: points cloud \
                The CarsDataset contains:

            - N x M Delayed tiles \
                Each tile will be a future xarray Dataset containing:

                - data : with keys : "x", "y", "z", "corr_msk"\
                    optional: "color", "msk", "z_inf", "z_sup"
                - attrs with keys: "margins", "epi_full_size", "epsg"
            - attributes containing: "disp_lower_bound",  "disp_upper_bound", \
                "elevation_delta_lower_bound","elevation_delta_upper_bound"

        :rtype: Tuple(CarsDataset, CarsDataset)
        """

        # Default orchestrator
        if orchestrator is None:
            # Create default sequential orchestrator for current application
            # be awere, no out_json will be shared between orchestrators
            # No files saved
            self.orchestrator = ocht.Orchestrator(
                orchestrator_conf={"mode": "sequential"}
            )
        else:
            self.orchestrator = orchestrator

        if source_pc_names is None:
            source_pc_names = ["PAIR_0"]

        if pair_dump_dir is None:
            pair_dump_dir = os.path.join(self.orchestrator.out_dir, "tmp")

        # Get local conf left image for this in_json iteration
        conf_left_img = sensor_image_left[sens_cst.INPUT_IMG]
        # Check left image and raise a warning
        # if different left images are used along with snap_to_img1 mode
        if self.ref_left_img is None:
            self.ref_left_img = conf_left_img
        else:
            if self.snap_to_img1 and self.ref_left_img != conf_left_img:
                logging.warning(
                    "snap_to_left_image mode is used but inputs "
                    "have different images as their "
                    "left image in pair. This may result in "
                    "increasing registration discrepancies between pairs"
                )

        # Add log about geoid
        if geoid_path is not None:
            alt_reference = "geoid"
        else:
            alt_reference = "ellipsoid"

        # Add infos to orchestrator.out_json
        updating_dict = {
            application_constants.APPLICATION_TAG: {
                pair_key: {
                    triangulation_constants.TRIANGULATION_RUN_TAG: {
                        triangulation_constants.ALT_REFERENCE_TAG: alt_reference
                    },
                }
            }
        }
        self.orchestrator.update_out_info(updating_dict)

        sensor1 = sensor_image_left[sens_cst.INPUT_IMG]
        sensor2 = sensor_image_right[sens_cst.INPUT_IMG]
        geomodel1 = sensor_image_left[sens_cst.INPUT_GEO_MODEL]
        geomodel2 = sensor_image_right[sens_cst.INPUT_GEO_MODEL]

        if self.snap_to_img1:
            grid_right = uncorrected_grid_right
            if grid_right is None:
                logging.error(
                    "Uncorrected grid was not given in order to snap it to img1"
                )

        # Compute disp_min and disp_max location for epipolar grid

        # Transform
        disp_min_tiling = epipolar_disparity_map.attributes["disp_min_tiling"]
        disp_max_tiling = epipolar_disparity_map.attributes["disp_max_tiling"]

        # change to N+1 M+1 dimension, fitting to tiling
        (
            disp_min_tiling,
            disp_max_tiling,
        ) = tiling.transform_disp_range_grid_to_two_layers(
            disp_min_tiling, disp_max_tiling
        )
        (
            epipolar_grid_min,
            epipolar_grid_max,
        ) = grids.compute_epipolar_grid_min_max(
            geometry_plugin,
            tiling.transform_four_layers_to_two_layers_grid(
                epipolar_image.tiling_grid
            ),
            sensor1,
            sensor2,
            geomodel1,
            geomodel2,
            grid_left,
            grid_right,
            epsg,
            disp_min_tiling,
            disp_max_tiling,
        )
        # update attributes for corresponding tiles in cloud fusion
        # TODO remove with refactoring
        pc_attributes = {
            "used_epsg_for_terrain_grid": epsg,
            "epipolar_grid_min": epipolar_grid_min,
            "epipolar_grid_max": epipolar_grid_max,
            "largest_epipolar_region": epipolar_image.attributes[
                "largest_epipolar_region"
            ],
            "source_pc_names": source_pc_names,
            "source_pc_name": pair_key,
            "color_type": epipolar_image.attributes["color_type"],
            "opt_epipolar_tile_size": epipolar_image.attributes["tile_width"],
        }

        if geoid_path:
            pc_attributes["geoid"] = (geoid_path,)

        if epipolar_disparity_map.dataset_type not in ("arrays", "points"):
            raise RuntimeError(
                "Triangulation application doesn't support this input "
                "data format"
            )

        # Create CarsDataset
        # Epipolar_point_cloud
        epipolar_points_cloud = cars_dataset.CarsDataset(
            epipolar_disparity_map.dataset_type,
            name="triangulation_" + pair_key,
        )
        epipolar_points_cloud.create_empty_copy(epipolar_image)
        epipolar_points_cloud.overlaps *= 0  # Margins removed

        # Update attributes to get epipolar info
        epipolar_points_cloud.attributes.update(pc_attributes)

        # Save objects
        # if isinstance(epipolar_points_cloud, xr.DataArray):
        if epipolar_disparity_map.dataset_type == "arrays":
            self.save_triangulation_output(
                epipolar_points_cloud,
                sensor_image_left,
                pair_output_dir,
                pair_dump_dir if self.save_intermediate_data else None,
                intervals,
                save_output_color,
                save_output_classification,
                save_output_mask,
                save_output_filling,
                save_output_performance_map,
            )

        else:
            safe_makedirs(pair_dump_dir)

            self.orchestrator.add_to_save_lists(
                os.path.join(pair_dump_dir, "depth_map"),
                cst.POINTS_CLOUD_MATCHES,
                epipolar_points_cloud,
                cars_ds_name="depth_map_x",
            )

        # Get saving infos in order to save tiles when they are computed
        [saving_info] = self.orchestrator.get_saving_infos(
            [epipolar_points_cloud]
        )

        # Generate Point clouds

        # Determining if a lower disparity inf corresponds to a lower or higher
        # hgt. It depends on the image pairing and geometrical models.
        if (
            intervals is not None
        ) and geometry_plugin.sensors_arrangement_left_right(
            sensor1, sensor2, geomodel1, geomodel2, grid_left, grid_right
        ):
            intervals[0], intervals[1] = intervals[1], intervals[0]

        # broadcast grids
        broadcasted_grid_left = self.orchestrator.cluster.scatter(grid_left)
        broadcasted_grid_right = self.orchestrator.cluster.scatter(grid_right)

        for col in range(epipolar_disparity_map.shape[1]):
            for row in range(epipolar_disparity_map.shape[0]):
                if epipolar_disparity_map[row, col] is not None:
                    # update saving infos  for potential replacement
                    full_saving_info = ocht.update_saving_infos(
                        saving_info, row=row, col=col
                    )
                    # Compute points
                    (
                        epipolar_points_cloud[row][col]
                    ) = self.orchestrator.cluster.create_task(
                        triangulation_wrapper
                    )(
                        epipolar_disparity_map[row, col],
                        sensor1,
                        sensor2,
                        geomodel1,
                        geomodel2,
                        broadcasted_grid_left,
                        broadcasted_grid_right,
                        geometry_plugin,
                        epsg,
                        geoid_path=geoid_path,
                        denoising_overload_fun=denoising_overload_fun,
                        cloud_id=cloud_id,
                        intervals=intervals,
                        saving_info=full_saving_info,
                    )

        return epipolar_points_cloud


def triangulation_wrapper(
    disparity_object: xr.Dataset,
    sensor1,
    sensor2,
    geomodel1,
    geomodel2,
    grid1,
    grid2,
    geometry_plugin,
    epsg,
    geoid_path=None,
    denoising_overload_fun=None,
    cloud_id=None,
    intervals=None,
    saving_info=None,
) -> Dict[str, Tuple[xr.Dataset, xr.Dataset]]:
    """
    Compute points clouds from image objects and disparity objects.

    :param disparity_object: Left disparity map dataset with :
            - cst_disp.MAP
            - cst_disp.VALID
            - cst.EPI_COLOR
    :type disparity_object: xr.Dataset
    :param sensor1: path to left sensor image
    :type sensor1: str
    :param sensor2: path to right sensor image
    :type sensor2: str
    :param geomodel1: path and attributes for left geomodel
    :type geomodel1: dict
    :param geomodel2: path and attributes for right geomodel
    :type geomodel2: dict
    :param grid1: dataset of the reference image grid file
    :type grid1: CarsDataset
    :param grid2: dataset of the secondary image grid file
    :type grid2: CarsDataset
    :param geometry_plugin: geometry plugin to use
    :type geometry_plugin: AbstractGeometry
    :param geoid_path: Geoid used for altimetric reference. Defaults to None
        for using ellipsoid as altimetric reference.
    :type geoid_path: str
    :param intervals: Either None or a List of 2 intervals indicators
        :type intervals: None or [str, str]
    :param denoising_overload_fun: function to overload dataset
    :type denoising_overload_fun: fun

    :return: Left disparity object

    Returned object is composed of :
        - dataset with :
            - cst.X
            - cst.Y
            - cst.Z
            - cst.EPI_COLOR
            - cst.Z_INF (optional)
            - cst.Z_SUP (optional)
    """

    # Get disparity maps
    disp_ref = disparity_object

    # Triangulate
    if isinstance(disp_ref, xr.Dataset):
        # Triangulate epipolar dense disparities
        points = triangulation_tools.triangulate(
            geometry_plugin,
            sensor1,
            sensor2,
            geomodel1,
            geomodel2,
            grid1,
            grid2,
            disp_ref,
        )

        if intervals is not None:
            points_inf = triangulation_tools.triangulate(
                geometry_plugin,
                sensor1,
                sensor2,
                geomodel1,
                geomodel2,
                grid1,
                grid2,
                disp_ref,
                disp_key=intervals[0],
            )

            points_sup = triangulation_tools.triangulate(
                geometry_plugin,
                sensor1,
                sensor2,
                geomodel1,
                geomodel2,
                grid1,
                grid2,
                disp_ref,
                disp_key=intervals[1],
            )

            points[cst.STEREO_REF][cst.Z_INF] = points_inf[cst.STEREO_REF][
                cst.Z
            ]
            points[cst.STEREO_REF][cst.Z_SUP] = points_sup[cst.STEREO_REF][
                cst.Z
            ]

    elif isinstance(disp_ref, pandas.DataFrame):
        # Triangulate epipolar sparse matches
        points = {}
        points[cst.STEREO_REF] = triangulation_tools.triangulate_matches(
            geometry_plugin,
            sensor1,
            sensor2,
            geomodel1,
            geomodel2,
            grid1,
            grid2,
            disp_ref.to_numpy(),
        )
    else:
        logging.error(
            "Disp ref is neither xarray Dataset  nor pandas DataFrame"
        )
        raise TypeError(
            "Disp ref is neither xarray Dataset  nor pandas DataFrame"
        )

    if geoid_path is not None:  # if user pass a geoid, use it as alt reference
        for key, point in points.items():
            points[key] = triangulation_tools.geoid_offset(point, geoid_path)

    # Fill datasets
    pc_dataset = points[cst.STEREO_REF]
    pc_dataset.attrs["cloud_id"] = cloud_id

    # Overload dataset with denoising fun
    if denoising_overload_fun is not None:
        if isinstance(pc_dataset, xr.Dataset):
            denoising_overload_fun(
                pc_dataset,
                sensor1,
                sensor2,
                geomodel1,
                geomodel2,
                grid1,
                grid2,
                geometry_plugin,
                disp_ref,
            )
        else:
            raise RuntimeError("wrong pc type for denoising func")

    attributes = None
    if isinstance(disp_ref, pandas.DataFrame):
        # Conversion to UTM
        projection.points_cloud_conversion_dataframe(
            points[cst.STEREO_REF], points[cst.STEREO_REF].attrs[cst.EPSG], epsg
        )
        cloud_epsg = epsg
        pc_dataset.attrs["epsg"] = cloud_epsg
        attributes = {
            "save_points_cloud_as_laz": True,
            "epsg": cloud_epsg,
            "color_type": None,
        }
        cars_dataset.fill_dataframe(
            pc_dataset, saving_info=saving_info, attributes=attributes
        )
    else:
        cars_dataset.fill_dataset(
            pc_dataset,
            saving_info=saving_info,
            window=cars_dataset.get_window_dataset(disparity_object),
            profile=cars_dataset.get_profile_rasterio(disparity_object),
            attributes=attributes,
            overlaps=cars_dataset.get_overlaps_dataset(disparity_object),
        )

    return pc_dataset

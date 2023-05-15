#!/usr/bin/env python
# coding: utf8
#
# Copyright (c) 2023 Centre National d'Etudes Spatiales (CNES).
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
Test module for cars/applications/point_cloud_outliers_removing/statistical.py
"""

import json_checker

# Third party imports
import pytest

# CARS imports
from cars.applications.point_cloud_outliers_removing.statistical import (
    Statistical,
)


@pytest.mark.unit_tests
def test_check_conf_with_error():
    """
    Test configuration check for outliers removing application
    with forbidden value for parameter k
    """
    conf = {
        "method": "statistical",
        "k": 0,  # should be > 0
    }
    with pytest.raises(json_checker.core.exceptions.DictCheckerError):
        _ = Statistical(conf)

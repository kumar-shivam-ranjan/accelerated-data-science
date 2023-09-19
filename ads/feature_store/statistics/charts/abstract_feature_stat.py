#!/usr/bin/env python
# -*- coding: utf-8; -*-
# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
from abc import abstractmethod

from ads.common.decorator.runtime_dependency import OptionalDependency

try:
    from plotly.graph_objs import Figure
except ModuleNotFoundError:
    raise ModuleNotFoundError(
        f"The `plotly` module was not found. Please run `pip install "
        f"{OptionalDependency.FEATURE_STORE}`."
    )


class AbsFeatureStat:
    @abstractmethod
    def add_to_figure(self, fig: Figure, xaxis: int, yaxis: int):
        pass

    @classmethod
    @abstractmethod
    def from_json(cls, json_dict: dict):
        pass

    @staticmethod
    def get_x_y_str_axes(xaxis: int, yaxis: int) -> ():
        return (
            ("xaxis" + str(xaxis + 1)),
            ("yaxis" + str(yaxis + 1)),
            ("x" + str(xaxis + 1)),
            ("y" + str(yaxis + 1)),
        )
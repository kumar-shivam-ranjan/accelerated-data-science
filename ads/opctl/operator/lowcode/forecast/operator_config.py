#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import os
from dataclasses import dataclass, field
from typing import Dict, List

from ads.common.serializer import DataClassSerializable
from ads.opctl.operator.common.utils import _load_yaml_from_uri
from ads.opctl.operator.operator_config import OperatorConfig

from .const import SupportedMetrics


@dataclass(repr=True)
class InputData(DataClassSerializable):
    """Class representing operator specification input data details."""

    format: str = None
    columns: List[str] = None
    url: str = None
    options: Dict = None
    limit: int = None


@dataclass(repr=True)
class TestData(DataClassSerializable):
    """Class representing operator specification test data details."""

    connect_args: Dict = None
    format: str = None
    columns: List[str] = None
    url: str = None
    name: str = None
    options: Dict = None


@dataclass(repr=True)
class OutputDirectory(DataClassSerializable):
    """Class representing operator specification output directory details."""

    connect_args: Dict = None
    format: str = None
    url: str = None
    name: str = None
    options: Dict = None


@dataclass(repr=True)
class DateTimeColumn(DataClassSerializable):
    """Class representing operator specification date time column details."""

    name: str = None
    format: str = None


@dataclass(repr=True)
class Horizon(DataClassSerializable):
    """Class representing operator specification horizon details."""

    periods: int = None
    interval: int = None
    interval_unit: str = None


@dataclass(repr=True)
class Tuning(DataClassSerializable):
    """Class representing operator specification tuning details."""

    n_trials: int = None


@dataclass(repr=True)
class ForecastOperatorSpec(DataClassSerializable):
    """Class representing forecast operator specification."""

    name: str = None
    historical_data: InputData = field(default_factory=InputData)
    additional_data: InputData = field(default_factory=InputData)
    test_data: TestData = field(default_factory=TestData)
    output_directory: OutputDirectory = field(default_factory=OutputDirectory)
    report_file_name: str = None
    report_title: str = None
    report_theme: str = None
    metrics_filename: str = None
    forecast_filename: str = None
    target_column: str = None
    feature_engineering: bool = None
    datetime_column: DateTimeColumn = field(default_factory=DateTimeColumn)
    target_category_columns: List[str] = field(default_factory=list)
    horizon: Horizon = field(default_factory=Horizon)
    model: str = None
    model_kwargs: Dict = field(default_factory=dict)
    confidence_interval_width: float = None
    metric: str = None
    tuning: Tuning = field(default_factory=Tuning)

    def __post_init__(self):
        """Adjusts the specification details."""
        self.metric = (self.metric or "").lower() or SupportedMetrics.SMAPE.lower()
        self.confidence_interval_width = self.confidence_interval_width or 0.80
        self.report_file_name = self.report_file_name or "report.html"
        self.feature_engineering = self.feature_engineering if self.feature_engineering is not None else True
        self.report_theme = self.report_theme or "light"
        self.metrics_filename = self.metrics_filename or "metrics.csv"
        self.forecast_filename = self.forecast_filename or "forecast.csv"
        self.target_column = self.target_column or "Sales"
        self.model_kwargs = self.model_kwargs or dict()


@dataclass(repr=True)
class ForecastOperatorConfig(OperatorConfig):
    """Class representing forecast operator config.

    Attributes
    ----------
    kind: str
        The kind of the resource. For operators it is always - `operator`.
    type: str
        The type of the operator. For forecast operator it is always - `forecast`
    version: str
        The version of the operator.
    spec: ForecastOperatorSpec
        The forecast operator specification.
    """

    kind: str = "operator"
    type: str = "forecast"
    version: str = "v1"
    spec: ForecastOperatorSpec = field(default_factory=ForecastOperatorSpec)

    @classmethod
    def _load_schema(cls) -> str:
        """Loads operator schema."""
        return _load_yaml_from_uri(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.yaml")
        )
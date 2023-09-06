#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

from ads.common.extended_enum import ExtendedEnumMeta


class SupportedModels(str, metaclass=ExtendedEnumMeta):
    """Supported forecast models."""

    Prophet = "prophet"
    Arima = "arima"
    NeuralProphet = "neuralprophet"
    AutoMLX = "automlx"


class SupportedMetrics(str, metaclass=ExtendedEnumMeta):
    """Supported forecast metrics."""

    MAPE = "MAPE"
    RMSE = "RMSE"
    MSE = "MSE"
    SMAPE = "sMAPE"
    WMAPE = "wMAPE"
    R2 = "r2"
    EXPLAINED_VARIANCE = "Explained Variance"
    MEAN_MAPE = "Mean MAPE" 
    MEAN_RMSE = "Mean RMSE"
    MEAN_MSE = "Mean MSE"
    MEAN_SMAPE = "Mean sMAPE"
    MEAN_WMAPE = "Mean wMAPE"
    MEAN_R2 = "Mean r2"
    MEAN_EXPLAINED_VARIANCE = "Mean Explained Variance"
    MEDIAN_MAPE = "Median MAPE" 
    MEDIAN_RMSE = "Median RMSE"
    MEDIAN_MSE = "Median MSE"
    MEDIAN_SMAPE = "Median sMAPE"
    MEDIAN_WMAPE = "Median wMAPE"
    MEDIAN_R2 = "Median r2"
    MEDIAN_EXPLAINED_VARIANCE = "Median Explained Variance"
    ELAPSED_TIME = "Elapsed Time"


MAX_COLUMNS_AUTOMLX = 15
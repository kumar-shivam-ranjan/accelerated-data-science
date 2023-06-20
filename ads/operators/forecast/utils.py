#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import json
import logging
import os
import sys
from ads.jobs.builders.runtimes.python_runtime import PythonRuntime
import pandas as pd
from urllib.parse import urlparse
import json
import yaml


import ads
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

import oci
import time
from datetime import datetime
from sklearn.metrics import (
    mean_absolute_percentage_error,
    explained_variance_score,
    r2_score,
    mean_squared_error,
)
import fsspec

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def _preprocess_prophet(data, ds_column, datetime_format):
    data["ds"] = pd.to_datetime(data[ds_column], format=datetime_format)
    return data.drop([ds_column], axis=1)


def smape(actual, predicted) -> float:
    if not all([isinstance(actual, np.ndarray), isinstance(predicted, np.ndarray)]):
        actual, predicted = (np.array(actual),)
        np.array(predicted)

    return round(
        np.mean(np.abs(actual - predicted) / (np.abs(actual) + np.abs(predicted)))
        * 100,
        2,
    )


def _call_pandas_fsspec(pd_fn, filename, storage_options, **kwargs):
    if fsspec.utils.get_protocol(filename) == "file":
        return pd_fn(filename, **kwargs)
    return pd_fn(filename, storage_options=storage_options, **kwargs)


def _load_data(filename, format, storage_options, columns, **kwargs):
    if not format:
        _, format = os.path.splitext(filename)
        format = format[1:]
    if format in ["json", "clipboard", "excel", "csv", "feather", "hdf"]:
        read_fn = getattr(pd, f"read_{format}")
        data = _call_pandas_fsspec(read_fn, filename, storage_options=storage_options)
        if columns:
            # keep only these columns, done after load because only CSV supports stream filtering
            data = data[columns]
        return data
    raise ValueError(f"Unrecognized format: {format}")


def _write_data(data, filename, format, storage_options, **kwargs):
    if not format:
        _, format = os.path.splitext(filename)
        format = format[1:]
    if format in ["json", "clipboard", "excel", "csv", "feather", "hdf"]:
        write_fn = getattr(data, f"to_{format}")
        return _call_pandas_fsspec(write_fn, filename, storage_options=storage_options)
    raise ValueError(f"Unrecognized format: {format}")


def _clean_data(data, target_columns, datetime_column, target_category_column=None):
    # Todo: KNN Imputer?
    if target_category_column is not None:
        df = pd.DataFrame()
        new_target_columns = []
        for col in target_columns:
            categories = data[target_category_column].unique()
            for cat in categories:
                data_cat = data[data[target_category_column] == cat].rename(
                    {col: f"{col}_{cat}"}, axis=1
                )
                data_cat_clean = data_cat.drop(
                    target_category_column, axis=1
                ).set_index(datetime_column)
                df = pd.concat([df, data_cat_clean], axis=1)
                new_target_columns.append(f"{col}_{cat}")
        df = df.reset_index()
        return df.fillna(0), new_target_columns
    else:
        raise ValueError(
            f"Either target_columns, target_category_column, or datetime_column not specified."
        )
    return data.fillna(0), target_columns


def _clean_merge_data(
    data,
    target_columns,
    datetime_column,
    target_category_column=None,
    additional_data=None,
):
    # Todo: KNN Imputer?
    df_by_target = dict()
    target_column_mappings = dict()
    categories = []

    if target_category_column is None:
        for col in target_columns:
            if additional_data is None:
                df_by_target[col] = data.fillna(0)
            else:
                df_by_target[col] = pd.concat(
                    [
                        data.set_index(datetime_column).fillna(0),
                        additional_data.set_index(datetime_column).fillna(0),
                    ],
                    axis=1,
                ).reset_index()
            target_column_mappings[col] = (col, None)
        return df_by_target, target_columns, target_column_mappings, categories

    categories = data[target_category_column].unique()
    for col in target_columns:
        for cat in categories:  # Note to restrict, add [:2]
            data_by_cat = data[data[target_category_column] == cat].rename(
                {col: f"{col}_{cat}"}, axis=1
            )
            data_by_cat_clean = (
                data_by_cat.drop(target_category_column, axis=1)
                .set_index(datetime_column)
                .fillna(0)
            )

            if additional_data is not None:
                data_add_by_cat = additional_data[
                    additional_data[target_category_column] == cat
                ].rename({col: f"{col}_{cat}"}, axis=1)
                data_add_by_cat_clean = (
                    data_add_by_cat.drop(target_category_column, axis=1)
                    .set_index(datetime_column)
                    .fillna(0)
                )
                data_by_cat_clean = pd.concat(
                    [data_add_by_cat_clean, data_by_cat_clean], axis=1
                )

            df_by_target[f"{col}_{cat}"] = data_by_cat_clean.reset_index()
            target_column_mappings[f"{col}_{cat}"] = (col, cat)

    new_target_columns = list(df_by_target.keys())
    return df_by_target, new_target_columns, target_column_mappings, categories


def load_data_dict(operator):
    """
    load_data_dict takes in an operator and returns the same operator.
    It adds/updates the operators "data_dict" attribute to be a dictionary of {target_name: dataset with 1) that target 2) exogeneous variables 3) datatime}
    """
    data = _load_data(
        operator.input_filename,
        operator.historical_data.get("format"),
        operator.storage_options,
        columns=operator.historical_data.get("columns"),
    )
    operator.original_user_data = data.copy()
    operator.original_total_data = data

    additional_data = None
    if operator.additional_filename is not None:
        additional_data = _load_data(
            operator.additional_filename,
            operator.additional_data.get("format"),
            operator.storage_options,
            columns=operator.additional_data.get("columns"),
        )
        operator.original_additional_data = additional_data.copy()
        operator.original_total_data = pd.concat([data, additional_data], axis=1)
    (
        full_data_dict,
        operator.target_columns,
        operator.target_column_mappings,
        operator.categories,
    ) = _clean_merge_data(
        data=data,
        target_columns=operator.target_columns,
        datetime_column=operator.ds_column,
        target_category_column=operator.target_category_column,
        additional_data=additional_data,
    )

    # data = _preprocess_arima(data, operator.ds_column, operator.datetime_format)
    operator.full_data_dict = full_data_dict
    return operator


def _build_metrics_df(y_true, y_pred, colunm_name):
    metrics = dict()
    metrics["sMAPE"] = smape(actual=y_true, predicted=y_pred)
    metrics["MAPE"] = mean_absolute_percentage_error(y_true=y_true, y_pred=y_pred)
    metrics["RMSE"] = np.sqrt(mean_squared_error(y_true=y_true, y_pred=y_pred))
    metrics["r2"] = r2_score(y_true=y_true, y_pred=y_pred)
    metrics["Explained Variance"] = explained_variance_score(
        y_true=y_true, y_pred=y_pred
    )
    return pd.DataFrame.from_dict(metrics, orient="index", columns=[colunm_name])


def evaluate_metrics(target_columns, data, outputs, target_col="yhat"):
    total_metrics = pd.DataFrame()
    for idx, col in enumerate(target_columns):
        y_true = np.asarray(data[col])
        y_pred = np.asarray(outputs[idx][target_col][: len(y_true)])

        metrics_df = _build_metrics_df(y_true=y_true, y_pred=y_pred, colunm_name=col)
        total_metrics = pd.concat([total_metrics, metrics_df], axis=1)
    return total_metrics


def test_evaluate_metrics(
    target_columns, test_filename, outputs, operator, target_col="yhat"
):
    total_metrics = pd.DataFrame()
    data = _load_data(
        test_filename,
        operator.test_data.get("format"),
        operator.storage_options,
        columns=operator.test_data.get("columns"),
    )
    data = _preprocess_prophet(data, operator.ds_column, operator.datetime_format)
    data, confirm_targ_columns = _clean_data(
        data=data,
        target_columns=operator.original_target_columns,
        target_category_column=operator.target_category_column,
        datetime_column="ds",
    )

    for idx, col in enumerate(target_columns):
        y_true = np.asarray(data[col])
        y_pred = np.asarray(outputs[idx][target_col][-len(y_true) :])

        metrics_df = _build_metrics_df(y_true=y_true, y_pred=y_pred, colunm_name=col)
        total_metrics = pd.concat([total_metrics, metrics_df], axis=1)
    summary_metrics = pd.DataFrame(
        {
            "Mean sMAPE": np.mean(total_metrics.loc["sMAPE"]),
            "Median sMAPE": np.median(total_metrics.loc["sMAPE"]),
            "Mean MAPE": np.mean(total_metrics.loc["MAPE"]),
            "Median MAPE": np.median(total_metrics.loc["MAPE"]),
            "Mean RMSE": np.mean(total_metrics.loc["RMSE"]),
            "Median RMSE": np.median(total_metrics.loc["RMSE"]),
            "Mean r2": np.mean(total_metrics.loc["r2"]),
            "Median r2": np.median(total_metrics.loc["r2"]),
            "Mean Explained Variance": np.mean(total_metrics.loc["Explained Variance"]),
            "Median Explained Variance": np.median(
                total_metrics.loc["Explained Variance"]
            ),
            "Elapsed Time": operator.elapsed_time,
        },
        index=["All Targets"],
    )
    return total_metrics, summary_metrics, data


def get_forecast_plots(
    data,
    outputs,
    target_columns,
    test_data=None,
    ds_col=None,
    ds_forecast_col=None,
    forecast_col_name="yhat",
    ci_col_names=None,
    ci_interval_width=0.95,
):
    import plotly.express as px
    from plotly import graph_objects as go
    import datapane as dp

    if ds_forecast_col is None:
        ds_forecast_col = ds_col

    def get_select_plot_list(fn):
        return dp.Select(
            blocks=[
                dp.Plot(fn(i, col), label=col) for i, col in enumerate(target_columns)
            ]
        )

    def plot_forecast_plotly(idx, col):
        fig = go.Figure()
        if ci_col_names is not None:
            fig.add_traces(
                [
                    go.Scatter(
                        x=ds_forecast_col,
                        y=outputs[idx][ci_col_names[0]],
                        mode="lines",
                        line_color="rgba(0,0,0,0)",
                        showlegend=False,
                    ),
                    go.Scatter(
                        x=ds_forecast_col,
                        y=outputs[idx][ci_col_names[1]],
                        mode="lines",
                        line_color="rgba(0,0,0,0)",
                        name=f"{ci_interval_width*100}% confidence interval",
                        fill="tonexty",
                        fillcolor="rgba(211, 211, 211, 0.5)",
                    ),
                ]
            )
        fig.add_trace(
            go.Scatter(
                x=ds_col,
                y=data[col],
                mode="markers",
                marker_color="black",
                name="Historical",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=ds_forecast_col,
                y=outputs[idx][forecast_col_name],
                mode="lines+markers",
                line_color="blue",
                name="Forecast",
            )
        )
        fig.add_vline(
            x=ds_col[-1:].values[0], line_width=1, line_dash="dash", line_color="gray"
        )
        return fig

    return get_select_plot_list(plot_forecast_plotly)

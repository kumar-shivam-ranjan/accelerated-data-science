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
    if ds_column != "ds":
        data.drop([ds_column], axis=1, inplace=True)
    return data


def _label_encode_dataframe(df, no_encode=set()):
    from ads.dataset.label_encoder import DataFrameLabelEncoder

    df_to_encode = df[list(set(df.columns) - no_encode)]
    le = DataFrameLabelEncoder().fit(df_to_encode)
    return le, le.transform(df)


def _inverse_transform_dataframe(le, df):
    return le.inverse_transform(df)


def smape(actual, predicted) -> float:
    if not all([isinstance(actual, np.ndarray), isinstance(predicted, np.ndarray)]):
        actual, predicted = (np.array(actual), np.array(predicted))
    return round(
        np.mean(np.abs(actual - predicted) / (np.abs(actual) + np.abs(predicted)))
        * 100,
        2,
    )


def human_time_friendly(seconds):
    TIME_DURATION_UNITS = (
        ("week", 60 * 60 * 24 * 7),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("min", 60),
        ("sec", 1),
    )
    if seconds == 0:
        return "inf"
    accumulator = []
    for unit, div in TIME_DURATION_UNITS:
        amount, seconds = divmod(int(seconds), div)
        if amount > 0:
            accumulator.append(
                "{} {}{}".format(amount, unit, "" if amount == 1 else "s")
            )
    return ", ".join(accumulator)


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
        return _call_pandas_fsspec(
            write_fn, filename, index=False, storage_options=storage_options
        )
    raise ValueError(f"Unrecognized format: {format}")


def _merge_category_columns(data, target_category_columns):
    return data.apply(
        lambda x: "__".join([str(x[col]) for col in target_category_columns]), axis=1
    )


def _clean_data(data, target_column, datetime_column, target_category_columns=None):
    # Todo: KNN Imputer?
    if target_category_columns is not None:

        data["__Series__"] = _merge_category_columns(data, target_category_columns)
        unique_categories = data["__Series__"].unique()

        df = pd.DataFrame()
        new_target_columns = []

        for cat in unique_categories:
            data_cat = data[data["__Series__"] == cat].rename(
                {target_column: f"{target_column}_{cat}"}, axis=1
            )
            data_cat_clean = data_cat.drop("__Series__", axis=1).set_index(
                datetime_column
            )
            df = pd.concat([df, data_cat_clean[f"{target_column}_{cat}"]], axis=1)
            new_target_columns.append(f"{target_column}_{cat}")
        df = df.reset_index().rename({"index": "ds"}, axis=1)
        return df.fillna(0), new_target_columns

    else:
        raise ValueError(
            f"Either target_columns, target_category_columns, or datetime_column not specified."
        )
    return data.fillna(0), target_column


def _build_indexed_datasets(
    data,
    target_column,
    datetime_column,
    target_category_columns=None,
    additional_data=None,
    metadata_data=None,
):
    df_by_target = dict()
    categories = []
    data_long = None
    data_wide = None

    if target_category_columns is None:
        if additional_data is None:
            df_by_target[target_column] = data.fillna(0)
        else:
            df_by_target[target_column] = pd.concat(
                [
                    data.set_index(datetime_column).fillna(0),
                    additional_data.set_index(datetime_column).fillna(0),
                ],
                axis=1,
            ).reset_index()
        return df_by_target, target_column, categories

    data["__Series__"] = _merge_category_columns(data, target_category_columns)
    unique_categories = data["__Series__"].unique()

    for cat in unique_categories:
        data_by_cat = data[data["__Series__"] == cat].rename(
            {target_column: f"{target_column}_{cat}"}, axis=1
        )
        data_by_cat_clean = (
            data_by_cat.drop(target_category_columns + ["__Series__"], axis=1)
            .set_index(datetime_column)
            .fillna(0)
        )
        if additional_data is not None:
            additional_data["__Series__"] = _merge_category_columns(
                additional_data, target_category_columns
            )
            data_add_by_cat = additional_data[
                additional_data["__Series__"] == cat
            ].rename({target_column: f"{target_column}_{cat}"}, axis=1)
            data_add_by_cat_clean = (
                data_add_by_cat.drop(target_category_columns + ["__Series__"], axis=1)
                .set_index(datetime_column)
                .fillna(0)
            )
            data_by_cat_clean = pd.concat(
                [data_add_by_cat_clean, data_by_cat_clean], axis=1
            )
        df_by_target[f"{target_column}_{cat}"] = data_by_cat_clean.reset_index()

    new_target_columns = list(df_by_target.keys())
    return df_by_target, new_target_columns, unique_categories


def load_data_dict(operator):
    """
    load_data_dict takes in an operator and returns the same operator.
    It adds/updates the operators "data_dict" attribute to be a dictionary of {target_name: dataset with 1) that target 2) exogeneous variables 3) datetime}
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
        operator.full_data_dict,
        operator.target_columns,
        operator.categories,
    ) = _build_indexed_datasets(
        data=data,
        target_column=operator.target_column,
        datetime_column=operator.ds_column,
        target_category_columns=operator.target_category_columns,
        additional_data=additional_data,
    )
    # data = _preprocess_arima(data, operator.ds_column, operator.datetime_format)
    return operator


def _build_metrics_df(y_true, y_pred, column_name, weights_denominator):
    metrics = dict()
    weight = np.sum(y_true) / weights_denominator
    mape = mean_absolute_percentage_error(y_true=y_true, y_pred=y_pred)
    metrics["WMAPE"] = weight * mape
    metrics["sMAPE"] = smape(actual=y_true, predicted=y_pred)
    metrics["MAPE"] = mape
    metrics["RMSE"] = np.sqrt(mean_squared_error(y_true=y_true, y_pred=y_pred))
    metrics["r2"] = r2_score(y_true=y_true, y_pred=y_pred)
    metrics["Explained Variance"] = explained_variance_score(
        y_true=y_true, y_pred=y_pred
    )
    return pd.DataFrame.from_dict(metrics, orient="index", columns=[column_name])


def evaluate_metrics(target_columns, data, outputs, target_col="yhat"):
    total_metrics = pd.DataFrame()
    weights_denominator = np.sum(np.abs(data[target_columns].values))
    for idx, col in enumerate(target_columns):
        y_true = np.asarray(data[col])
        y_pred = np.asarray(outputs[idx][target_col][: len(y_true)])

        metrics_df = _build_metrics_df(
            y_true=y_true,
            y_pred=y_pred,
            column_name=col,
            weights_denominator=weights_denominator,
        )
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
        target_column=operator.original_target_column,
        target_category_columns=operator.target_category_columns,
        datetime_column="ds",
    )
    missing_from_test_set = set(target_columns) - set(confirm_targ_columns)
    if missing_from_test_set:
        logger.warn(
            f"Missing data in the test data set for the following categories: {missing_from_test_set}"
        )
    extra_in_test_set = set(confirm_targ_columns) - set(target_columns)
    if extra_in_test_set:
        logger.warn(
            f"Extra categories found in the test data set for the following categories: {extra_in_test_set}"
        )
    test_target_columns = list(set(target_columns) - missing_from_test_set)

    weights_denominator = np.sum(np.abs(data[test_target_columns].values))

    period_metrics = None
    for idx, col in enumerate(target_columns):
        try:
            y_true = np.asarray(data[col])
        except:
            logger.warn(
                f"Could not find category: {col} in test dataset when building metrics. Available categories: {data.columns}"
            )
        y_pred = np.asarray(outputs[idx][target_col][-len(y_true) :])

        metrics_df = _build_metrics_df(
            y_true=y_true,
            y_pred=y_pred,
            column_name=col,
            weights_denominator=weights_denominator,
        )
        period_metrics_i = None
        for j in data.index:
            period_metrics_j = _build_metrics_df(
                y_true=[y_true[j]],
                y_pred=[y_pred[j]],
                column_name=data["ds"].values[j],
                weights_denominator=weights_denominator,
            )
            period_metrics_i = pd.concat([period_metrics_i, period_metrics_j], axis=1)
        period_metrics = pd.concat([period_metrics, period_metrics_i])
        print(f"period_metrics_i: {period_metrics_i}")
        total_metrics = pd.concat([total_metrics, metrics_df], axis=1)
    print(f"period_metrics: {period_metrics}")
    summary_by_period = None
    for i in period_metrics.index.unique():
        summary_by_period_i = dict()
        for j in data["ds"].values:
            summary_by_period_i[j] = np.mean(
                period_metrics[j][period_metrics.index == i].values
            )
        summary_by_period = pd.concat(
            [
                summary_by_period,
                pd.DataFrame.from_dict(
                    summary_by_period_i, orient="index", columns=[i]
                ),
            ],
            axis=1,
        )
    summary_metrics_dict = {
        f"Mean {met}": list(summary_by_period[met].values)
        + [np.mean(total_metrics.loc[met])]
        for met in ["WMAPE", "sMAPE", "MAPE", "RMSE", "r2", "Explained Variance"]
    }
    # "Mean sMAPE": [np.mean(total_metrics.loc["sMAPE"])].append(summary_by_period["sMAPE"].values),
    # "Median sMAPE": [np.median(total_metrics.loc["sMAPE"])].append(summary_by_period["sMAPE"].values),
    # "Mean MAPE": [np.mean(total_metrics.loc["MAPE"])].append(summary_by_period["MAPE"].values),
    # "Median MAPE": [np.median(total_metrics.loc["MAPE"])].append(summary_by_period["MAPE"].values),
    # "Mean RMSE": [np.mean(total_metrics.loc["RMSE"])].append(summary_by_period["RMSE"].values),
    # "Median RMSE": [np.median(total_metrics.loc["RMSE"])].append(summary_by_period["RMSE"].values),
    # "Mean r2": [np.mean(total_metrics.loc["r2"])].append(summary_by_period["r2"].values),
    # "Median r2": [np.median(total_metrics.loc["r2"])].append(summary_by_period["r2"].values),
    # "Mean Explained Variance": [np.mean(total_metrics.loc["Explained Variance"])].append(summary_by_period["Explained Variance"].values),
    # "Median Explained Variance":[np.median(
    #     total_metrics.loc["Explained Variance"]
    # )].append(summary_by_period["Explained Variance"].values),
    # "Elapsed Time": [operator.elapsed_time for _ in range(len(data["ds"].values)+1)],
    summary_metrics = pd.DataFrame(
        summary_metrics_dict,
        index=[str(x) for x in data["ds"].values] + ["All Targets"],
    )
    summary_metrics["Elapsed Time"] = operator.elapsed_time
    return total_metrics, summary_metrics, data


def get_forecast_plots(
    historical_data,
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
        if test_data is not None:
            try:
                fig.add_trace(
                    go.Scatter(
                        x=test_data["ds"],
                        y=test_data[col],
                        mode="markers",
                        marker_color="green",
                        name="Actual",
                    )
                )
            except:
                logger.warn(
                    f"Could not find category: {col} in test dataset when building plots. Available categories: {test_data.columns}"
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
        fig.add_trace(
            go.Scatter(
                x=ds_col,
                y=historical_data[col],
                mode="markers",
                marker_color="black",
                name="Historical",
            )
        )
        fig.add_vline(
            x=ds_col[-1:].values[0], line_width=1, line_dash="dash", line_color="gray"
        )
        return fig

    return get_select_plot_list(plot_forecast_plotly)

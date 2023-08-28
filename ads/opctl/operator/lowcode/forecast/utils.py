#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/


import os

import datapane as dp
import fsspec
import numpy as np
import pandas as pd
import plotly.express as px
from plotly import graph_objects as go
from sklearn.metrics import (
    explained_variance_score,
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
)

from ads.dataset.label_encoder import DataFrameLabelEncoder
from .const import SupportedModels, MAX_COLUMNS_AUTOMLX


def _label_encode_dataframe(df, no_encode=set()):
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
            df = pd.concat([df, data_cat_clean], axis=1)
            new_target_columns.append(f"{target_column}_{cat}")
        df = df.reset_index()
        return df.fillna(0), new_target_columns

    raise ValueError(
        f"Either target_columns, target_category_columns, or datetime_column not specified."
    )


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


def _build_metrics_df(y_true, y_pred, column_name):
    metrics = dict()
    metrics["sMAPE"] = smape(actual=y_true, predicted=y_pred)
    metrics["MAPE"] = mean_absolute_percentage_error(y_true=y_true, y_pred=y_pred)
    metrics["RMSE"] = np.sqrt(mean_squared_error(y_true=y_true, y_pred=y_pred))
    metrics["r2"] = r2_score(y_true=y_true, y_pred=y_pred)
    metrics["Explained Variance"] = explained_variance_score(
        y_true=y_true, y_pred=y_pred
    )
    return pd.DataFrame.from_dict(metrics, orient="index", columns=[column_name])


def evaluate_metrics(target_columns, data, outputs, target_col="yhat"):
    total_metrics = pd.DataFrame()
    for idx, col in enumerate(target_columns):
        y_true = np.asarray(data[col])
        y_pred = np.asarray(outputs[idx][target_col][: len(y_true)])

        metrics_df = _build_metrics_df(y_true=y_true, y_pred=y_pred, column_name=col)
        total_metrics = pd.concat([total_metrics, metrics_df], axis=1)
    return total_metrics


def _select_plot_list(fn, target_columns):
    return dp.Select(
        blocks=[dp.Plot(fn(i, col), label=col) for i, col in enumerate(target_columns)]
    )


def _add_unit(num, unit):
    return f"{num} {unit}"


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
    if ds_forecast_col is None:
        ds_forecast_col = ds_col

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
            fig.add_trace(
                go.Scatter(
                    x=test_data["ds"],
                    y=test_data[col],
                    mode="markers",
                    marker_color="green",
                    name="Actual",
                )
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

    return _select_plot_list(plot_forecast_plotly, target_columns)


def human_time_friendly(seconds):
    TIME_DURATION_UNITS = (
        ("week", 60 * 60 * 24 * 7),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("min", 60)
    )
    if seconds == 0:
        return "inf"
    accumulator = []
    for unit, div in TIME_DURATION_UNITS:
        amount, seconds = divmod(float(seconds), div)
        if amount > 0:
            accumulator.append(
                "{} {}{}".format(int(amount), unit, "" if amount == 1 else "s")
            )
    accumulator.append("{} secs".format(round(seconds, 2)))
    return ", ".join(accumulator)

def select_auto_model(columns):
    if columns!=None and len(columns) > MAX_COLUMNS_AUTOMLX:
        return SupportedModels.Arima
    return SupportedModels.AutoMLX
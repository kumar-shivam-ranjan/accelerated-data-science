#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import json
import logging
import os
import sys
from ads.jobs.builders.runtimes.python_runtime import PythonRuntime
import datapane as dp
from statsmodels.tsa.arima.model import ARIMA
import pmdarima as pm
import pandas as pd
from ads.operators.forecast.utils import (
    load_data_dict,
    _write_data,
    _label_encode_dataframe,
)

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def operate(operator):
    operator = load_data_dict(operator)
    full_data_dict = operator.full_data_dict

    # Extract the Confidence Interval Width and convert to arima's equivalent - alpha
    if operator.confidence_interval_width is None:
        operator.confidence_interval_width = 1 - operator.model_kwargs.get(
            "alpha", 0.05
        )
    model_kwargs = operator.model_kwargs
    model_kwargs["alpha"] = 1 - operator.confidence_interval_width

    models = []
    outputs = dict()
    outputs_legacy = []

    for i, (target, df) in enumerate(full_data_dict.items()):
        # format the dataframe for this target. Dropping NA on target[df] will remove all future data
        le, df_encoded = _label_encode_dataframe(
            df, no_encode={operator.ds_column, target}
        )

        df_encoded[operator.ds_column] = pd.to_datetime(
            df_encoded[operator.ds_column], format=operator.datetime_format
        )
        df_clean = df_encoded.set_index(operator.ds_column)
        data_i = df_clean[df_clean[target].notna()]

        # Assume that all columns passed in should be used as additional data
        additional_regressors = set(data_i.columns) - {target, operator.ds_column}
        print(f"Additional Regressors Detected {list(additional_regressors)}")

        # Split data into X and y for arima tune method
        y = data_i[target]
        X_in = None
        if len(additional_regressors):
            X_in = data_i.drop(target, axis=1)

        # Build and fit model
        model = pm.auto_arima(y=y, X=X_in, **operator.model_kwargs)

        # Build future dataframe
        start_date = y.index.values[-1]
        n_periods = operator.horizon.get("periods")
        interval_unit = operator.horizon.get("interval_unit")
        interval = int(operator.horizon.get("interval", 1))
        if len(additional_regressors):
            X = df_clean[df_clean[target].isnull()].drop(target, axis=1)
        else:
            X = pd.date_range(start=start_date, periods=n_periods, freq=interval_unit)
            X = X.iloc[::interval, :]

        # Predict and format forecast
        yhat, conf_int = model.predict(
            n_periods=n_periods,
            X=X,
            return_conf_int=True,
            alpha=model_kwargs["alpha"],
        )
        yhat_clean = pd.DataFrame(yhat, index=yhat.index, columns=["yhat"])
        conf_int_clean = pd.DataFrame(
            conf_int, index=yhat.index, columns=["yhat_lower", "yhat_upper"]
        )
        forecast = pd.concat([yhat_clean, conf_int_clean], axis=1)
        print(f"-----------------Model {i}----------------------")
        print(forecast[["yhat", "yhat_lower", "yhat_upper"]].tail())

        # Collect all outputs
        models.append(model)
        outputs_legacy.append(forecast)
        outputs[target] = forecast

    operator.models = models
    operator.outputs = outputs_legacy

    print("===========Done===========")
    outputs_merged = pd.DataFrame()

    # Merge the outputs from each model into 1 df with all outputs by target and category
    col = operator.original_target_column
    output_col = pd.DataFrame()
    yhat_upper_percentage = int(100 - model_kwargs["alpha"] * 100 / 2)
    yhat_lower_name = "p" + str(int(100 - yhat_upper_percentage))
    yhat_upper_name = "p" + str(yhat_upper_percentage)
    for cat in operator.categories:
        output_i = pd.DataFrame()

        output_i["Date"] = outputs[f"{col}_{cat}"].index
        output_i["Series"] = cat
        output_i[f"forecast_value"] = outputs[f"{col}_{cat}"]["yhat"].values
        output_i[yhat_upper_name] = outputs[f"{col}_{cat}"]["yhat_upper"].values
        output_i[yhat_lower_name] = outputs[f"{col}_{cat}"]["yhat_lower"].values
        output_col = pd.concat([output_col, output_i])
    # output_col = output_col.sort_values(operator.ds_column).reset_index(drop=True)
    output_col = output_col.reset_index(drop=True)
    outputs_merged = pd.concat([outputs_merged, output_col], axis=1)
    _write_data(
        outputs_merged, operator.output_filename, "csv", operator.storage_options
    )

    # Re-merge historical datas for processing
    data_merged = pd.concat(
        [
            v[v[k].notna()].set_index(operator.ds_column)
            for k, v in full_data_dict.items()
        ],
        axis=1,
    ).reset_index()
    return data_merged, models, outputs_legacy


def get_arima_report(operator):
    sec5_text = dp.Text(f"## ARIMA Model Parameters")
    sec5 = dp.Select(
        blocks=[
            dp.HTML(m.summary().as_html(), label=operator.target_columns[i])
            for i, m in enumerate(operator.models)
        ]
    )
    return [sec5_text, sec5]  # + [sec4_text, sec4]

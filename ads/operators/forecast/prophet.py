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
from prophet.plot import add_changepoints_to_plot
from prophet import Prophet
import pandas as pd
from ads.operators.forecast.utils import evaluate_metrics, _load_data, _clean_data, _write_data

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


def _preprocess_prophet(data, ds_column, datetime_format):
    data["ds"] = pd.to_datetime(data[ds_column], format=datetime_format)
    return data.drop([ds_column], axis=1)

def operate(operator):
    data = _load_data(operator.input_filename, operator.historical_data.get("format"), operator.storage_options, columns=operator.historical_data.get("columns"))
    data = _preprocess_prophet(data, operator.ds_column, operator.datetime_format)
    data, operator.target_columns = _clean_data(data=data, 
                                                target_columns=operator.target_columns, 
                                                target_category_column=operator.target_category_column, 
                                                datetime_column="ds")
    operator.data = data
    
    models = []
    outputs = []
    for i, col in enumerate(operator.target_columns):
        data_i = data[[col, "ds"]]
        data_i.rename({col:"y"}, axis=1, inplace=True)
        
        model = Prophet()
        model.fit(data_i)

        future = model.make_future_dataframe(periods=operator.horizon['periods']) #, freq=operator.horizon['interval_unit'])
        forecast = model.predict(future)

        print(f"-----------------Model {i}----------------------")
        print(forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail())
        models.append(model)
        outputs.append(forecast)
    
    operator.models = models
    operator.outputs = outputs

    print("===========Done===========")
    outputs_merged = outputs.copy()
    for i, col in enumerate(operator.target_columns):
        outputs_merged[i] = outputs_merged[i].rename(lambda x: x+"_"+col if x != 'ds' else x, axis=1)
    output_total = pd.concat(outputs_merged, axis=1)
    _write_data(output_total, operator.output_filename, "csv", operator.storage_options)
    return data, models, outputs


def get_prophet_report(self):

    # def get_select_plot_list(fn):
    #     return dp.Select(blocks=[dp.Plot(fn(i), label=col) for i, col in enumerate(self.target_columns)])
    
    # sec1_text = dp.Text(f"## Forecast Overview \nThese plots show your forecast in the context of historical data with 80% confidence.")
    # sec1 = get_select_plot_list(lambda idx: self.models[idx].plot(self.outputs[idx], include_legend=True))
    
    # sec2_text = dp.Text(f"## Forecast Broken Down by Trend Component")
    # sec2 = get_select_plot_list(lambda idx: self.models[idx].plot_components(self.outputs[idx]))
    
    # sec3_text = dp.Text(f"## Forecast Changepoints")
    # sec3_figs = [self.models[idx].plot(self.outputs[idx]) for idx in range(len(self.target_columns))]
    # [add_changepoints_to_plot(sec3_figs[idx].gca(), self.models[idx], self.outputs[idx]) for idx in range(len(self.target_columns))]
    # sec3 = get_select_plot_list(lambda idx: sec3_figs[idx])

    # # Auto-corr
    # sec4_text = dp.Text(f"## Auto-Correlation Plots")
    # output_series = []
    # for idx in range(len(self.target_columns)):
    #     series = pd.Series(self.outputs[idx]["yhat"])
    #     series.index = pd.DatetimeIndex(self.outputs[idx]["ds"])
    #     output_series.append(series)
    # sec4 = get_select_plot_list(lambda idx: pd.plotting.autocorrelation_plot(output_series[idx]))

    # sec5_text = dp.Text(f"## Forecast Seasonality Parameters")
    # sec5 = dp.Select(blocks=[dp.Table(pd.DataFrame(m.seasonalities), label=self.target_columns[i]) for i, m in enumerate(self.models)])
    
    return [] #[sec1_text, sec1, sec2_text, sec2, sec3_text, sec3, sec4_text, sec4, sec5_text, sec5]
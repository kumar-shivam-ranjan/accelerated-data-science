#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import os
import tempfile
import time
from abc import ABC, abstractmethod
from typing import Tuple

import fsspec
import pandas as pd
import numpy as np
from sklearn import linear_model

from ads.opctl import logger

from ..operator_config import AnomalyOperatorConfig, AnomalyOperatorSpec
from .anomaly_dataset import AnomalyDatasets, AnomalyOutput, TestData
from ads.opctl.operator.lowcode.anomaly.const import OutputColumns, SupportedMetrics
from ..const import SupportedModels
from ads.opctl.operator.lowcode.common.utils import (
    human_time_friendly,
    load_data,
    enable_print,
    disable_print,
    write_data,
    merge_category_columns,
    find_output_dirname,
)
from ads.opctl.operator.lowcode.anomaly.utils import _build_metrics_df, default_signer
from ads.common.object_storage_details import ObjectStorageDetails


class AnomalyOperatorBaseModel(ABC):
    """The base class for the anomaly detection operator models."""

    def __init__(self, config: AnomalyOperatorConfig, datasets: AnomalyDatasets):
        """Instantiates the AnomalyOperatorBaseModel instance.

        Properties
        ----------
        config: AnomalyOperatorConfig
            The anomaly detection operator configuration.
        """

        self.config: AnomalyOperatorConfig = config
        self.spec: AnomalyOperatorSpec = config.spec
        self.datasets = datasets
        if self.spec.validation_data is not None:
            self.X_valid_dict = self.datasets.valid_data.X_valid_dict
            self.y_valid_dict = self.datasets.valid_data.y_valid_dict
        else:
            self.X_valid_dict = None
            self.y_valid_dict = None

    def generate_report(self):
        """Generates the report."""
        import datapane as dp
        import matplotlib.pyplot as plt

        start_time = time.time()
        # fallback using sklearn oneclasssvm when the sub model _build_model fails
        try:
            anomaly_output = self._build_model()
        except Exception as e:
            anomaly_output = self._fallback_build_model()

        elapsed_time = time.time() - start_time

        summary_metrics = None
        total_metrics = None
        test_data = None

        if self.spec.test_data:
            test_data = TestData(self.spec)
            total_metrics, summary_metrics = self._test_data_evaluate_metrics(
                anomaly_output, test_data, elapsed_time
            )
        table_blocks = [
            dp.DataTable(df, label=col)
            for col, df in self.datasets.full_data_dict.items()
        ]
        data_table = (
            dp.Select(blocks=table_blocks) if len(table_blocks) > 1 else table_blocks[0]
        )
        date_column = self.spec.datetime_column.name

        blocks = []
        for target, df in self.datasets.full_data_dict.items():
            figure_blocks = []
            time_col = df[date_column].reset_index(drop=True)
            anomaly_col = anomaly_output.get_anomalies_by_cat(category=target)[
                OutputColumns.ANOMALY_COL
            ]
            columns = set(df.columns).difference({date_column})
            for col in columns:
                y = df[col].reset_index(drop=True)
                fig, ax = plt.subplots(figsize=(8, 3), layout="constrained")
                ax.grid()
                ax.plot(time_col, y, color="black")
                for i, index in enumerate(anomaly_col):
                    if anomaly_col[i] == 1:
                        ax.scatter(time_col[i], y[i], color="red", marker="o")
                plt.xlabel(date_column)
                plt.ylabel(col)
                plt.title(f"`{col}` with reference to anomalies")
                figure_blocks.append(ax)
            blocks.append(dp.Group(blocks=figure_blocks, label=target))
        plots = dp.Select(blocks=blocks) if len(blocks) > 1 else blocks[0]

        report_sections = []
        title_text = dp.Text("# Anomaly Detection Report")

        yaml_appendix_title = dp.Text(f"## Reference: YAML File")
        yaml_appendix = dp.Code(code=self.config.to_yaml(), language="yaml")
        summary = dp.Blocks(
            blocks=[
                dp.Group(
                    dp.Text(f"You selected the **`{self.spec.model}`** model."),
                    dp.Text(
                        "Based on your dataset, you could have also selected "
                        f"any of the models: `{'`, `'.join(SupportedModels.keys())}`."
                    ),
                    dp.BigNumber(
                        heading="Analysis was completed in ",
                        value=human_time_friendly(elapsed_time),
                    ),
                    label="Summary",
                )
            ]
        )
        sec_text = dp.Text(f"## Train Evaluation Metrics")
        sec = dp.DataTable(self._evaluation_metrics(anomaly_output))
        evaluation_metrics_sec = [sec_text, sec]

        test_metrics_sections = []
        if total_metrics is not None and not total_metrics.empty:
            sec_text = dp.Text(f"## Test Data Evaluation Metrics")
            sec = dp.DataTable(total_metrics)
            test_metrics_sections = test_metrics_sections + [sec_text, sec]

        if summary_metrics is not None and not summary_metrics.empty:
            sec_text = dp.Text(f"## Test Data Summary Metrics")
            sec = dp.DataTable(summary_metrics)
            test_metrics_sections = test_metrics_sections + [sec_text, sec]

        report_sections = (
            [title_text, summary]
            + [plots]
            + [data_table]
            + evaluation_metrics_sec
            + test_metrics_sections
            + [yaml_appendix_title, yaml_appendix]
        )

        # save the report and result CSV
        self._save_report(
            report_sections=report_sections,
            anomaly_output=anomaly_output,
            test_metrics=total_metrics,
        )

    def _evaluation_metrics(self, anomaly_output):
        total_metrics = pd.DataFrame()
        for cat in anomaly_output.list_categories():
            num_anomalies = anomaly_output.get_num_anomalies_by_cat(cat)
            metrics_df = pd.DataFrame.from_dict(
                {"Num of Anomalies": num_anomalies}, orient="index", columns=[cat]
            )
            total_metrics = pd.concat([total_metrics, metrics_df], axis=1)
        return total_metrics

    def _test_data_evaluate_metrics(self, anomaly_output, test_data, elapsed_time):
        total_metrics = pd.DataFrame()
        summary_metrics = pd.DataFrame()
        data = None
        try:
            data = load_data(
                filename=filename,
                format=self.spec.validation_data.format,
                columns=self.spec.validation_data.columns,
            )
        except pd.errors.EmptyDataError:
            logger.warn("The provided test data file was empty. Skipping test data.")
            return total_metrics, summary_metrics, None
        except InvalidParameterError as e:
            e.args = e.args + ("Invalid Parameter: test_data",)
            logger.warn(
                f"The provided test data file was Invalid. Skipping test data. Full error message: {e.args}"
            )
            return total_metrics, summary_metrics, None

        if data.empty:
            return total_metrics, summary_metrics, None

        if self.spec.target_category_columns is not None:
            data["__Series__"] = utils._merge_category_columns(data, self.spec.target_category_columns)


        for cat in anomaly_output.list_categories():
            output = anomaly_output.category_map[cat][0]
            date_col = self.spec.datetime_column.name

            val_data = data[data["__Series__"] == cat] if '__Series__' in data else data
            val_data[date_col] = pd.to_datetime(val_data[date_col])
            test_data_i = test_data.get_data_for_series(cat)

            dates = output[output[date_col].isin(test_data_i[date_col])][date_col]

            metrics_df = _build_metrics_df(
                test_data_i[test_data_i[date_col].isin(dates)][
                    OutputColumns.ANOMALY_COL
                ].values,
                output[output[date_col].isin(dates)][OutputColumns.ANOMALY_COL].values,
                cat,
            )
            total_metrics = pd.concat([total_metrics, metrics_df], axis=1)

        if total_metrics.empty:
            return total_metrics, summary_metrics

        summary_metrics = pd.DataFrame(
            {
                SupportedMetrics.MEAN_RECALL: np.mean(
                    total_metrics.loc[SupportedMetrics.RECALL]
                ),
                SupportedMetrics.MEDIAN_RECALL: np.median(
                    total_metrics.loc[SupportedMetrics.RECALL]
                ),
                SupportedMetrics.MEAN_PRECISION: np.mean(
                    total_metrics.loc[SupportedMetrics.PRECISION]
                ),
                SupportedMetrics.MEDIAN_PRECISION: np.median(
                    total_metrics.loc[SupportedMetrics.PRECISION]
                ),
                SupportedMetrics.MEAN_ACCURACY: np.mean(
                    total_metrics.loc[SupportedMetrics.ACCURACY]
                ),
                SupportedMetrics.MEDIAN_ACCURACY: np.median(
                    total_metrics.loc[SupportedMetrics.ACCURACY]
                ),
                SupportedMetrics.MEAN_F1_SCORE: np.mean(
                    total_metrics.loc[SupportedMetrics.F1_SCORE]
                ),
                SupportedMetrics.MEDIAN_F1_SCORE: np.median(
                    total_metrics.loc[SupportedMetrics.F1_SCORE]
                ),
                SupportedMetrics.MEAN_ROC_AUC: np.mean(
                    total_metrics.loc[SupportedMetrics.ROC_AUC]
                ),
                SupportedMetrics.MEDIAN_ROC_AUC: np.median(
                    total_metrics.loc[SupportedMetrics.ROC_AUC]
                ),
                SupportedMetrics.MEAN_PRC_AUC: np.mean(
                    total_metrics.loc[SupportedMetrics.PRC_AUC]
                ),
                SupportedMetrics.MEDIAN_PRC_AUC: np.median(
                    total_metrics.loc[SupportedMetrics.PRC_AUC]
                ),
                SupportedMetrics.ELAPSED_TIME: elapsed_time,
            },
            index=["All Targets"],
        )

        return total_metrics, summary_metrics

    def _save_report(
        self,
        report_sections: Tuple,
        anomaly_output: AnomalyOutput,
        test_metrics: pd.DataFrame,
    ):
        """Saves resulting reports to the given folder."""
        import datapane as dp

        unique_output_dir = find_output_dirname(self.spec.output_directory)

        if ObjectStorageDetails.is_oci_path(unique_output_dir):
            storage_options = default_signer()
        else:
            storage_options = dict()

        # datapane html report
        with tempfile.TemporaryDirectory() as temp_dir:
            report_local_path = os.path.join(temp_dir, "___report.html")
            disable_print()
            dp.save_report(report_sections, report_local_path)
            enable_print()
            with open(report_local_path) as f1:
                with fsspec.open(
                    os.path.join(unique_output_dir, self.spec.report_file_name),
                    "w",
                    **storage_options,
                ) as f2:
                    f2.write(f1.read())

        if self.spec.generate_inliers:
            inliers = anomaly_output.get_inliers(self.datasets.data)
            write_data(
                data=inliers,
                filename=os.path.join(unique_output_dir, self.spec.inliers_filename),
                format="csv",
                storage_options=storage_options,
            )

        outliers = anomaly_output.get_outliers(self.datasets.data)
        write_data(
            data=outliers,
            filename=os.path.join(unique_output_dir, self.spec.outliers_filename),
            format="csv",
            storage_options=storage_options,
        )

        if test_metrics is not None and not test_metrics.empty:
            write_data(
                data=test_metrics.rename_axis("metrics").reset_index(),
                filename=os.path.join(
                    unique_output_dir, self.spec.test_metrics_filename
                ),
                format="csv",
                storage_options=storage_options,
            )

        logger.warn(
            f"The report has been successfully "
            f"generated and placed to the: {unique_output_dir}."
        )

    def _fallback_build_model(self):
        """
        Fallback method for the sub model _build_model method.
        """
        logger.warn(
            "The build_model method has failed for the model: {}. "
            "A fallback model will be built.".format(self.spec.model)
        )

        date_column = self.spec.datetime_column.name
        dataset = self.datasets

        anomaly_output = AnomalyOutput(date_column=date_column)

        # map the output as per anomaly dataset class, 1: outlier, 0: inlier
        self.outlier_map = {1: 0, -1: 1}

        # Iterate over the full_data_dict items
        for target, df in self.datasets.full_data_dict.items():
            est = linear_model.SGDOneClassSVM(random_state=42)
            est.fit(df[target].values.reshape(-1, 1))
            y_pred = np.vectorize(self.outlier_map.get)(est.predict(df[target].values.reshape(-1, 1)))
            scores = est.score_samples(df[target].values.reshape(-1, 1))

            anomaly = pd.DataFrame({
                date_column: df[date_column],
                OutputColumns.ANOMALY_COL: y_pred
            }).reset_index(drop=True)
            score = pd.DataFrame({
                date_column: df[date_column],
                OutputColumns.SCORE_COL: scores
            }).reset_index(drop=True)
            anomaly_output.add_output(target, anomaly, score)

        return anomaly_output

    @abstractmethod
    def _generate_report(self):
        """
        Generates the report for the particular model.
        The method that needs to be implemented on the particular model level.
        """

    @abstractmethod
    def _build_model(self) -> pd.DataFrame:
        """
        Build the model.
        The method that needs to be implemented on the particular model level.
        """

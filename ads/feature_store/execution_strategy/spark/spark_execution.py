#!/usr/bin/env python
# -*- coding: utf-8; -*-

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import logging
import pandas as pd

from ads.common.decorator.runtime_dependency import OptionalDependency
from ads.feature_store.common.utils.utility import get_features
from ads.feature_store.execution_strategy.engine.spark_engine import SparkEngine

try:
    from pyspark.sql import DataFrame
except ModuleNotFoundError:
    raise ModuleNotFoundError(
        f"The `pyspark` module was not found. Please run `pip install "
        f"{OptionalDependency.SPARK}`."
    )
except Exception as e:
    raise

from ads.feature_store.common.enums import (
    FeatureStoreJobType,
    LifecycleState,
    EntityType,
)
from ads.feature_store.common.spark_session_singleton import SparkSessionSingleton
from ads.feature_store.common.utils.feature_schema_mapper import (
    convert_pandas_datatype_with_schema,
)
from ads.feature_store.common.utils.transformation_utils import TransformationUtils
from ads.feature_store.data_validation.great_expectation import ExpectationService
from ads.feature_store.dataset_job import DatasetJob
from ads.feature_store.execution_strategy.delta_lake.delta_lake_service import (
    DeltaLakeService,
)
from ads.feature_store.execution_strategy.execution_strategy import Strategy
from ads.feature_store.feature_group_job import FeatureGroupJob
from ads.feature_store.transformation import Transformation

from ads.feature_store.feature_statistics.statistics_service import StatisticsService

logger = logging.getLogger(__name__)


class SparkExecutionException(Exception):
    """
    `SparkExecutionException` is raised during invalid spark execution
    """

    pass


class SparkExecutionEngine(Strategy):
    """The SparkExecutionEngine class is a strategy class that provides methods to ingest, delete, and write data in
    a Spark cluster. It uses Apache Spark to perform operations on data and supports Delta Lake, an open-source
    storage layer that brings ACID transactions to Apache Spark and big data workloads. The class has methods to
    ingest feature definitions and datasets, delete feature definitions and datasets, and write data to Delta Lake
    tables. It also provides utility methods to check if a Delta Lake table exists and retrieve the columns of a
    Delta Lake table.
    """

    def __init__(self, metastore_id: str = None):
        self._spark_session = SparkSessionSingleton(metastore_id).get_spark_session()
        self._spark_context = self._spark_session.sparkContext
        self.spark_engine = SparkEngine(metastore_id)
        self.delta_lake_service = DeltaLakeService(self._spark_session)
        self._jvm = self._spark_context._jvm

    def ingest_feature_definition(
        self, feature_group, feature_group_job: FeatureGroupJob, dataframe
    ):
        try:
            self._save_offline_dataframe(dataframe, feature_group, feature_group_job)
        except Exception as e:
            raise SparkExecutionException(e).with_traceback(e.__traceback__)

    def ingest_dataset(self, dataset, dataset_job: DatasetJob):
        try:
            self._save_dataset_input(dataset, dataset_job)
        except Exception as e:
            raise SparkExecutionException(e).with_traceback(e.__traceback__)

    def delete_feature_definition(
        self, feature_group, feature_group_job: FeatureGroupJob
    ):
        """
        Deletes a feature definition from the system.

        Args:
            feature_group (object): An object representing a group of related features.
            feature_group_job (FeatureGroupJob): An object representing a job responsible for processing the feature group.
        """

        try:
            # Get the database and table that need to be deleted
            database = feature_group.entity_id
            table = feature_group.name

            # Delete the related entities from the database
            self.spark_engine.remove_table_and_database(database, table)

            feature_group.oci_feature_group.delete()

        except Exception as ex:
            error_details = str(ex)
            logger.error(f"Deletion Failed with : {type(ex)} with error message: {ex}")

            output_details = {"error_details": error_details}

            self._update_job_and_parent_details(
                parent_entity=feature_group,
                job_entity=feature_group_job,
                output_details=output_details,
            )

    def delete_dataset(self, dataset, dataset_job: DatasetJob):
        """
        Deletes a dataset from the system.

        Args:
            dataset (object): An object representing a group of related features.
            dataset_job (FeatureGroupJob): An object representing a job responsible for processing the feature group.
        """

        try:
            # Get the database and table that need to be deleted
            database = dataset.entity_id
            table = dataset.name

            self.spark_engine.remove_table_and_database(database, table)

            # Delete the related entities from the database
            dataset.oci_dataset.delete()

        except Exception as ex:
            error_details = str(ex)
            logger.error(f"Deletion Failed with : {type(ex)} with error message: {ex}")

            output_details = {"error_details": error_details}

            self._update_job_and_parent_details(
                parent_entity=dataset,
                job_entity=dataset_job,
                output_details=output_details,
            )

    def _save_offline_dataframe(
        self, data_frame, feature_group, feature_group_job: FeatureGroupJob
    ):
        """Ingest dataframe to the feature store system. as now this handles both spark dataframe and pandas
        dataframe. in case of pandas after transformation we convert it to spark and write to the delta.

        Parameters
        ----------
        data_frame
            data_frame that needs to be ingested in the system.
        feature_group
            feature group.
        feature_group_job
            feature_group_job

        Returns
        -------
        None
        """

        error_details = None
        feature_statistics = None
        validation_output = None
        output_features = []

        try:
            # Create database in hive metastore if not exist
            database = feature_group.entity_id
            self.spark_engine.create_database(database)

            if isinstance(data_frame, pd.DataFrame):
                if not feature_group.is_infer_schema:
                    convert_pandas_datatype_with_schema(
                        feature_group.input_feature_details, data_frame
                    )

            # TODO: Get event timestamp column and apply filtering basis from and to timestamp

            # Apply validations
            validation_output = ExpectationService.apply_validations(
                expectation_details=feature_group.expectation_details,
                expectation_suite_name=feature_group.name,
                dataframe=data_frame,
            )

            # Apply the transformation
            if feature_group.transformation_id:
                logger.info("Dataframe is transformation enabled.")
                # Loads the transformation resource
                transformation = Transformation.from_id(feature_group.transformation_id)

                featured_data = TransformationUtils.apply_transformation(
                    self._spark_session, data_frame, transformation
                )
            else:
                logger.info("Transformation not defined.")
                featured_data = data_frame

            if isinstance(featured_data, pd.DataFrame):
                featured_data = (
                    self.spark_engine.convert_from_pandas_to_spark_dataframe(
                        featured_data
                    )
                )

            target_table = f"{database}.{feature_group.name}"
            self.delta_lake_service.write_dataframe_to_delta_lake(
                featured_data,
                target_table,
                feature_group.primary_keys,
                feature_group_job.ingestion_mode,
                featured_data.schema,
                feature_group_job.feature_option_details,
            )

            # Get the output features
            output_features = get_features(
                self.spark_engine.get_columns_from_table(target_table), feature_group.id
            )

            logger.info(f"output features for the FeatureGroup: {output_features}")
            # Compute Feature Statistics

            feature_statistics = StatisticsService.compute_stats_with_mlm(
                statistics_config=feature_group.oci_feature_group.statistics_config,
                input_df=featured_data,
            )

        except Exception as ex:
            error_details = str(ex)
            logger.error(
                f"FeatureGroup Materialization Failed with : {type(ex)} with error message: {ex}"
            )

        output_details = {
            "error_details": error_details,
            "validation_output": validation_output,
            "commit_id": "commit_id",
            "feature_statistics": feature_statistics,
        }

        self._update_job_and_parent_details(
            parent_entity=feature_group,
            job_entity=feature_group_job,
            output_features=output_features,
            output_details=output_details,
        )

    def update_feature_definition_features(self, feature_group, target_table):
        """
        Updates the given feature group with output features extracted from the given target table.

        Args:
            feature_group (FeatureGroup): The feature group to be updated.
            target_table (str): The name of the target table.

        Raises:
            SparkExecutionException: If an error occurs during the update process.

        Returns:
            None
        """
        try:
            # Get the output features
            output_features = get_features(
                self.spark_engine.get_columns_from_table(target_table), feature_group.id
            )
            if output_features:
                feature_group._with_features(output_features)
            feature_group.update()
        except Exception as e:
            raise SparkExecutionException(e).with_traceback(e.__traceback__)

    def update_dataset_features(self, dataset, target_table):
        """
        Updates the given dataset with output features extracted from the given target table.

        Args:
            dataset (Dataset): The dataset to be updated.
            target_table (str): The name of the target table.

        Raises:
            SparkExecutionException: If an error occurs during the update process.

        Returns:
            None
        """

        try:
            # Get the output features
            output_features = get_features(
                output_columns=self.spark_engine.get_columns_from_table(target_table),
                parent_id=dataset.id,
                entity_type=EntityType.DATASET,
            )
            if output_features:
                dataset._with_features(output_features)
            dataset.update()
        except Exception as e:
            raise SparkExecutionException(e).with_traceback(e.__traceback__)

    def _save_dataset_input(self, dataset, dataset_job: DatasetJob):
        """As now this handles both spark dataframe and pandas dataframe. in case of pandas after transformation we
        convert it to spark and write to the delta.
        """

        error_details = None
        validation_output = None
        feature_statistics = None
        output_features = []
        database = (
            dataset.entity_id
        )  # Get the database and table name using entity_id and name of the dataset.
        target_table = f"{database}.{dataset.name}"

        try:
            # Execute the SQL query on the spark and load the dataframe.
            dataset_dataframe = self.spark_engine.sql(dataset.query)

            # Apply validations
            validation_output = ExpectationService.apply_validations(
                expectation_details=dataset.expectation_details,
                expectation_suite_name=dataset.name,
                dataframe=dataset_dataframe,
            )

            self.delta_lake_service.save_delta_dataframe(
                dataset_dataframe,
                dataset_job.ingestion_mode,
                target_table,
                dataset_job.feature_option_details,
            )

            # Get the output features
            output_features = get_features(
                output_columns=self.spark_engine.get_columns_from_table(target_table),
                parent_id=dataset.id,
                entity_type=EntityType.DATASET,
            )
            logger.info(f"output features for the dataset: {output_features}")

            # Compute Feature Statistics
            feature_statistics = StatisticsService.compute_stats_with_mlm(
                statistics_config=dataset.oci_dataset.statistics_config,
                input_df=dataset_dataframe,
            )

        except Exception as ex:
            error_details = str(ex)
            logger.error(
                f"Dataset Materialization Failed with : {type(ex)} with error message: {ex}"
            )

        output_details = {
            "error_details": error_details,
            "validation_output": validation_output,
            "commit_id": "commit_id",
            "feature_statistics": feature_statistics,
        }

        self._update_job_and_parent_details(
            parent_entity=dataset,
            job_entity=dataset_job,
            output_features=output_features,
            output_details=output_details,
        )

    @staticmethod
    def _update_job_and_parent_details(
        parent_entity, job_entity, output_features=None, output_details=None
    ):
        """
        Updates the parent and job entities with relevant details.

        Args:
            parent_entity: The parent entity, which can be a FeatureGroup or Dataset.
            job_entity: The corresponding job entity related to the parent, which can be a FeatureGroupJob or DatasetJob.
            output_features: A list of output features for the parent entity.
            output_details: Output details for the job entity.
            job_type: The type of job entity. Defaults to `FeatureStoreJobType.FEATURE_GROUP_INGESTION`.

        Returns:
            None
        """
        # Update the parent entity with output features.
        if output_features:
            parent_entity._with_features(output_features)

        # Complete the job entity with required details.
        job_entity._mark_job_complete(output_details)

        # Update both the parent and job entities.
        parent_entity.update()
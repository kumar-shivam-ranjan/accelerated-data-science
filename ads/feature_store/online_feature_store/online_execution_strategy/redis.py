from typing import OrderedDict, Any

from pyspark.sql.functions import col, concat_ws

from ads.feature_store.online_feature_store.online_feature_store_strategy import (
    OnlineFeatureStoreStrategy,
)


class OnlineRedisEngine(OnlineFeatureStoreStrategy):
    def write(self, feature_group, feature_group_job, dataframe):
        if len(feature_group.primary_keys["items"]) == 1:
            key = feature_group.primary_keys["items"][0]["name"]
            df_with_key = dataframe.withColumn("key", col(key))
        else:
            primary_keys = []
            for key in feature_group.primary_keys["items"]:
                primary_keys.append(key["name"])
            df_with_key = dataframe.withColumn("key", concat_ws(":", *primary_keys))
        df_with_key.write.format("org.apache.spark.sql.redis").option(
            "table", feature_group.id
        ).option("key.column", "key").save()

    def read(self, feature_group, keys: OrderedDict[str, Any]):
        ordered_keys = []

        for primary_key in feature_group.primary_keys["items"]:
            primary_key_name = primary_key["name"]
            if primary_key_name in keys:
                ordered_keys.append(keys[primary_key_name])
            else:
                raise KeyError(
                    f"'FeatureGroup' object has no primary key called {primary_key_name}."
                )
        ordered_concatenated_key = ":".join(ordered_keys)
        response = self.redis_client.hgetall(f"{self.id}:{ordered_concatenated_key}")
        return response

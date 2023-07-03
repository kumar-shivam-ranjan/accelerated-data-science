#!/usr/bin/env python
# -*- coding: utf-8; -*-

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

from ads.common.oci_mixin import OCIModelMixin
import oci.feature_store


class OCIFeatureStoreMixin(OCIModelMixin):
    @classmethod
    def init_client(
        cls, **kwargs
    ) -> oci.feature_store.feature_store_client.FeatureStoreClient:
        client = cls._init_client(
            client=oci.feature_store.feature_store_client.FeatureStoreClient, **kwargs
        )
        return client

    @property
    def client(self) -> oci.feature_store.feature_store_client.FeatureStoreClient:
        return super().client
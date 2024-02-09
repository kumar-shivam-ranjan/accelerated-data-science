#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2021, 2024 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse

import oci
from fsspec.callbacks import Callback, NoOpCallback
from ads.common import auth as authutil
from ads.common import oci_client


class InvalidObjectStoragePath(Exception):  # pragma: no cover
    """Invalid Object Storage Path."""

    pass


@dataclass
class ObjectStorageDetails:
    """Class that represents the Object Storage bucket URI details.

    Attributes
    ----------
    bucket: str
        The Object Storage bucket name.
    namespace: (str, optional). Defaults to empty string.
        The Object Storage namespace. Will be extracted automatically if not provided.
    filepath: (str, optional). Defaults to empty string.
        The path to the object.
    auth: (Dict, optional). Defaults to None.
        ADS auth dictionary for OCI authentication.
        This can be generated by calling ads.common.auth.api_keys() or ads.common.auth.resource_principal()
        If this is None, ads.common.default_signer() will be used.
    """

    bucket: str
    namespace: str = ""
    filepath: str = ""
    auth: Dict = None

    def __post_init__(self):
        if not self.auth:
            self.auth = authutil.default_signer()
        # Extract OS namespace if not provided.
        if not self.namespace:
            os_client = oci_client.OCIClientFactory(**self.auth).object_storage
            self.namespace = os_client.get_namespace().data

    def __repr__(self):
        return self.path

    @property
    def path(self):
        """Full object storage path of this file."""
        return os.path.join(
            "oci://",
            self.bucket + "@" + self.namespace,
            self.filepath.lstrip("/") if self.filepath else "",
        )

    @classmethod
    def from_path(cls, env_path: str) -> "ObjectStorageDetails":
        """Construct an ObjectStorageDetails instance from conda pack path.

        Parameters
        ----------
        env_path: (str)
            codna pack object storage path.

        Raises
        ------
        Exception: OCI conda url path not properly configured.

        Returns
        -------
        ObjectStorageDetails
            An ObjectStorageDetails instance.
        """
        try:
            url_parse = urlparse(env_path)
            bucket_name = url_parse.username
            namespace = url_parse.hostname
            object_name = url_parse.path.strip("/")
            return cls(bucket=bucket_name, namespace=namespace, filepath=object_name)
        except:
            raise Exception(
                "OCI path is not properly configured. "
                "It should follow the pattern `oci://<bucket-name>@<namespace>/object_path`."
            )

    def to_tuple(self):
        """Returns the values of the fields of ObjectStorageDetails class."""
        return self.bucket, self.namespace, self.filepath

    def fetch_metadata_of_object(self) -> Dict:
        """Fetches the manifest metadata from the object storage of a conda pack.

        Returns
        -------
        Dict
            The metadata in dictionary format.
        """
        os_client = oci_client.OCIClientFactory(**self.auth).object_storage
        res = os_client.get_object(self.namespace, self.bucket, self.filepath)
        metadata = res.data.headers["opc-meta-manifest"]
        metadata_json = json.loads(metadata)
        return metadata_json

    @staticmethod
    def is_valid_uri(uri: str) -> bool:
        """Validates the Object Storage URI."""
        if not re.match(r"oci://*@*", uri):
            raise InvalidObjectStoragePath(
                f"The `{uri}` is not a valid Object Storage path. "
                "It must follow the pattern `oci://<bucket_name>@<namespace>/<prefix>`."
            )
        return True

    @staticmethod
    def is_oci_path(uri: str = None) -> bool:
        """Check if the given path is oci object storage uri.

        Parameters
        ----------
        uri: str
            The URI of the target.

        Returns
        -------
        bool: return True if the path is oci object storage uri.
        """
        if not uri:
            return False
        return uri.lower().startswith("oci://")

    def is_bucket_versioned(self) -> bool:
        """Check if the given bucket is versioned.
        Returns
        -------
        bool: return True if the bucket is versioned.

        """
        os_client = oci_client.OCIClientFactory(**self.auth).object_storage
        res = os_client.get_bucket(
            namespace_name=self.namespace, bucket_name=self.bucket
        ).data
        return res.versioning == "Enabled"

    def list_objects(self, **kwargs):
        """Lists objects in a given oss path
        Returns
        -------
            Object of type oci.object_storage.models.ListObjects
        """
        fields = kwargs.pop(
            "fields",
            "name,etag,size,timeCreated,md5,timeModified,storageTier,archivalState",
        )

        os_client = oci_client.OCIClientFactory(**self.auth).object_storage
        objects = oci.pagination.list_call_get_all_results(
            os_client.list_objects,
            namespace_name=self.namespace,
            bucket_name=self.bucket,
            prefix=self.filepath,
            fields=fields,
            **kwargs,
        ).data
        return objects

    def list_object_versions(
        self,
        **kwargs,
    ):
        """Lists object versions in a given oss path

        Returns
        -------
            Object of type oci.object_storage.models.ObjectVersionCollection
        """
        fields = kwargs.pop(
            "fields",
            "name,etag,size,timeCreated,md5,timeModified,storageTier,archivalState",
        )

        os_client = oci_client.OCIClientFactory(**self.auth).object_storage
        objects = oci.pagination.list_call_get_all_results(
            os_client.list_object_versions,
            namespace_name=self.namespace,
            bucket_name=self.bucket,
            prefix=self.filepath,
            fields=fields,
            **kwargs,
        ).data
        return objects

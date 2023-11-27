#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

from unittest.mock import MagicMock, patch

import pytest
from oci.feature_store.models import Transformation
from oci.response import Response

from ads.common.oci_mixin import OCIModelMixin
from ads.feature_store.service.oci_transformation import (
    OCITransformation,
)

TRANSFORMATION_OCID = "ocid1.transformation.oc1.iad.xxx"

OCI_TRANSFORMATION_PAYLOAD = {
    "id": TRANSFORMATION_OCID,
    "compartment_id": "ocid1.compartment.oc1..xxx",
    "feature_store_id": "ocid1.featurestore.oc1.iad.xxx",
    "display_name": "transformation name",
    "description": "The transformation description",
    "source_code": "source",
    "lifecycle_state": "ACTIVE",
    "created_by": "ocid1.user.oc1..xxx",
    "time_created": "2022-08-24T17:07:39.200000Z",
}


class TestOCITransformation:
    def setup_class(cls):
        # Mock delete model response
        cls.mock_delete_transformation_response = Response(
            data=None, status=None, headers=None, request=None
        )

        # Mock create/update model response
        cls.mock_create_transformation_response = Response(
            data=Transformation(**OCI_TRANSFORMATION_PAYLOAD),
            status=None,
            headers=None,
            request=None,
        )

    def setup_method(self):
        self.mock_transformation = OCITransformation(**OCI_TRANSFORMATION_PAYLOAD)

    @pytest.fixture(scope="class")
    def mock_client(self):
        mock_client = MagicMock()
        mock_client.create_transformation = MagicMock(
            return_value=self.mock_create_transformation_response
        )
        mock_client.delete_transformation = MagicMock(
            return_value=self.mock_delete_transformation_response
        )
        return mock_client

    def test_create_fail(self):
        """Ensures creating model fails in case of wrong input params."""
        with pytest.raises(
            ValueError,
            match="The `compartment_id` must be specified.",
        ):
            OCITransformation().create()

    def test_create_success(self, mock_client):
        """Ensures creating model passes in case of valid input params."""
        with patch.object(OCITransformation, "client", mock_client):
            with patch.object(OCITransformation, "to_oci_model") as mock_to_oci_model:
                with patch.object(
                    OCITransformation, "update_from_oci_model"
                ) as mock_update_from_oci_model:
                    mock_update_from_oci_model.return_value = self.mock_transformation
                    mock_oci_transformation = Transformation(
                        **OCI_TRANSFORMATION_PAYLOAD
                    )
                    mock_to_oci_model.return_value = mock_oci_transformation
                    result = self.mock_transformation.create()
                    mock_client.create_transformation.assert_called_with(
                        mock_oci_transformation
                    )
                    assert result == self.mock_transformation

    @patch.object(OCIModelMixin, "from_ocid")
    def test_from_id(self, mock_from_ocid):
        """Tests getting a model by OCID."""
        OCITransformation.from_id(TRANSFORMATION_OCID)
        mock_from_ocid.assert_called_with(TRANSFORMATION_OCID)

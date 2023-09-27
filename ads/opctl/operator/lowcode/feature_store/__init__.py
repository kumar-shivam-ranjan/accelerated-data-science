#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import os

__operator_path__ = os.path.dirname(__file__)

__type__ = os.path.basename(__operator_path__.rstrip("/"))

__version__ = "v1"

__conda__ = f"{__type__}_{__version__}"

__conda_type__ = "custom"  # service/custom

__gpu__ = "no"  # yes/no

__keywords__ = []

__backends__ = []  # ["job","dataflow"]. The local backend will be supported by default.


__short_description__ = """
Oracle feature store is a stack based solution that is deployed in the customer enclave using OCI
resource manager. Customer can stand up the service with infrastructure in their own tenancy.
The service consists of API which are deployed in customer tenancy using resource manager.
"""

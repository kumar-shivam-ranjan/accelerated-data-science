#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

from typing import Dict

from .operator_config import OperatorConfig


def operate(operator_config: OperatorConfig) -> None:
    """Runs the operator."""
    print(operator_config)
    pass


def verify(spec: Dict, **kwargs: Dict) -> bool:
    """Verifies the operator config."""
    operator = OperatorConfig.from_dict(spec)
    msg_header = (
        f"{'*' * 50} The operator's config has been successfully verified {'*' * 50}"
    )
    print(msg_header)
    print(operator.to_yaml())
    print("*" * len(msg_header))

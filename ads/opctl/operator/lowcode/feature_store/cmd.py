#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

from typing import Dict

import click

from ads.opctl import logger
from ads.opctl.operator.common.utils import _load_yaml_from_uri
from ads.opctl.operator.common.operator_yaml_generator import YamlGenerator

from .const import SupportedModels


def init(**kwargs: Dict) -> str:
    """
    Generates operator config by the schema.

    Properties
    ----------
    kwargs: (Dict, optional).
        Additional key value arguments.

        - type: str
            The type of the operator.

    Returns
    -------
    str
        The YAML specification generated based on the schema.
    """
    logger.info("==== MLflow related options ====")

    # model_type = click.prompt(
    #     "Provide a model type:",
    #     type=click.Choice(SupportedModels.values()),
    #     default=SupportedModels.Prophet,
    # )

    return YamlGenerator(
        schema=_load_yaml_from_uri(__file__.replace("cmd.py", "schema.yaml"))
    ).generate_example(values={"type": kwargs.get("type")})

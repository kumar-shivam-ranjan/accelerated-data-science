#!/usr/bin/env python
# -*- coding: utf-8 -*--

# Copyright (c) 2023 Oracle and/or its affiliates.
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/

import json
import os
import sys
from typing import List

import yaml

from ads.opctl import logger
from ads.opctl.operator.common.const import ENV_OPERATOR_ARGS
from ads.opctl.operator.common.utils import _parse_input_args

from .operator import operate, verify
from .operator_config import AnomalyOperatorConfig


def main(raw_args: List[str]):
    """The entry point of the anomaly the operator."""
    args, _ = _parse_input_args(raw_args)
    if not args.file and not args.spec and not os.environ.get(ENV_OPERATOR_ARGS):
        logger.info(
            "Please specify -f[--file] or -s[--spec] or "
            f"pass operator's arguments via {ENV_OPERATOR_ARGS} environment variable."
        )
        return

    logger.info("-" * 100)
    logger.info(
        f"{'Running' if not args.verify else 'Verifying'} the anomaly detection operator."
    )

    # if spec provided as input string, then convert the string into YAML
    yaml_string = ""
    if args.spec or os.environ.get(ENV_OPERATOR_ARGS):
        operator_spec_str = args.spec or os.environ.get(ENV_OPERATOR_ARGS)
        try:
            yaml_string = yaml.safe_dump(json.loads(operator_spec_str))
        except json.JSONDecodeError:
            yaml_string = yaml.safe_dump(yaml.safe_load(operator_spec_str))
        except:
            yaml_string = operator_spec_str

    operator_config = AnomalyOperatorConfig.from_yaml(
        uri=args.file,
        yaml_string=yaml_string,
    )

    logger.info(operator_config.to_yaml())

    # run operator
    if args.verify:
        verify(operator_config)
    else:
        operate(operator_config)


if __name__ == "__main__":
    main(sys.argv[1:])

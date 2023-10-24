import importlib
import importlib.util
import json
import logging
import os
import pathlib
import sys
import yaml
from copy import deepcopy
from typing import Any, List, Optional
from langchain.chains.loading import load_chain_from_config, type_to_loader_dict
from langchain.llms.base import LLM
from langchain.schema.runnable import (
    Runnable,
    RunnableConfig,
    RunnableSequence,
)
from . import guardrails
from .guardrails.base import GuardrailIO, Guardrail, RunInfo


logger = logging.getLogger(__name__)
BLOCKED_MESSAGE = "custom_msg"
SPEC_CLASS = "class"
SPEC_PATH = "path"
SPEC_SPEC = "spec"
SPEC_CHAIN_TYPE = "_type"
SPEC_CHAIN = "chain"
BUILT_IN = "ads."


class GuardrailSequence(RunnableSequence):
    """Represents a sequence of guardrails and other LangChain (non-guardrail) components."""

    CHAIN_TYPE = "ads_guardrail_sequence"

    first: Optional[Runnable] = None
    last: Optional[Runnable] = None

    @property
    def steps(self) -> List[Runnable[Any, Any]]:
        """Steps in the sequence."""
        if self.first:
            chain = [self.first] + self.middle
        else:
            return []
        if self.last:
            chain += [self.last]
        return chain

    @classmethod
    def from_sequence(cls, sequence: RunnableSequence):
        return cls(first=sequence.first, middle=sequence.middle, last=sequence.last)

    def __or__(self, other) -> "GuardrailSequence":
        """Adds another component to the end of this sequence.
        If the sequence is empty, the component will be added as the first step of the sequence.
        """
        if not self.first:
            return GuardrailSequence(first=other)
        if not self.last:
            return GuardrailSequence(first=self.first, last=other)
        return self.from_sequence(super().__or__(other))

    def __ror__(self, other) -> "GuardrailSequence":
        """Chain this sequence to the end of another component."""
        return self.from_sequence(super().__ror__(other))

    def invoke(self, input: Any, config: RunnableConfig = None) -> GuardrailIO:
        """Invokes the guardrail.

        In LangChain interface, invoke() is designed for calling the chain with a single input,
        while batch() is designed for calling the chain with a list of inputs.
        https://python.langchain.com/docs/expression_language/interface

        """
        return self.run(input)

    def _invoke_llm(self, llm, texts, num_generations, **kwargs):
        if num_generations > 1:
            if len(texts) > 1:
                raise NotImplementedError(
                    "Batch completion with more than 1 prompt is not supported."
                )
            # TODO: invoke in parallel
            # TODO: let llm generate n completions.
            output = [llm.invoke(texts[0], **kwargs) for _ in range(num_generations)]
        else:
            output = llm.batch(texts, **kwargs)
        return output

    def run(self, input: Any, num_generations: int = 1, **kwargs) -> GuardrailIO:
        """Runs the guardrail sequence.

        Parameters
        ----------
        input : Any
            Input for the guardrail sequence.
            This will be the input for the first step in the sequence.
        num_generations : int, optional
            The number of completions to be generated by the LLM, by default 1.

        The kwargs will be passed to LLM step(s) in the guardrail sequence.

        Returns
        -------
        GuardrailIO
            Contains the outputs and metrics from each step.
            The final output is stored in GuardrailIO.data property.
        """
        obj = GuardrailIO(data=[input])

        for i, step in enumerate(self.steps):
            if not isinstance(step, Guardrail):
                # Invoke the step as a LangChain component
                spec = {}
                with RunInfo(name=step.__class__.__name__, input=obj.data) as info:
                    if isinstance(step, LLM):
                        output = self._invoke_llm(
                            step, obj.data, num_generations, **kwargs
                        )
                        spec.update(kwargs)
                        spec["num_generations"] = num_generations
                    else:
                        output = step.batch(obj.data)
                    info.output = output
                    info.parameters = {
                        "class": step.__class__.__name__,
                        "path": step.__module__,
                        "spec": spec,
                    }
                obj.info.append(info)
                obj.data = output
            else:
                obj = step.invoke(obj)
            if not obj.data:
                default_msg = f"Blocked by {step.__class__.__name__}"
                msg = getattr(step, BLOCKED_MESSAGE, default_msg)
                if msg is None:
                    msg = default_msg
                obj.data = [msg]
                return obj
        return obj

    def _save_to_file(self, chain_dict, filename, overwrite=False):
        expanded_path = os.path.expanduser(filename)
        if os.path.isfile(expanded_path) and not overwrite:
            raise FileExistsError(
                f"File {expanded_path} already exists."
                "Set overwrite to True if you would like to overwrite the file."
            )

        file_ext = pathlib.Path(expanded_path).suffix.lower()
        with open(expanded_path, "w", encoding="utf-8") as f:
            if file_ext == ".yaml":
                yaml.safe_dump(chain_dict, f, default_flow_style=False)
            elif file_ext == ".json":
                json.dump(chain_dict, f)
            else:
                raise ValueError(
                    f"{self.__class__.__name__} can only be saved as yaml or json format."
                )

    def save(self, filename: str = None, overwrite: bool = False):
        """Serialize the sequence to a dictionary.
        Optionally, save the sequence into a JSON or YAML file.

        The dictionary will look like the following::

            {
                "_type": "ads_guardrail_sequence",
                "chain": [
                    {
                        "class": "...",
                        "path": "...",
                        "spec": {
                            ...
                        }
                    }
                ]
            }

        Parameters
        ----------
        filename : str
            YAML or JSON filename to store the serialized sequence.

        Returns
        -------
        dict
            The sequence saved as a dictionary.
        """
        chain_spec = []
        for step in self.steps:
            class_name = step.__class__.__name__
            if step.__module__.startswith(BUILT_IN):
                path = getattr(step, "path", None)
            else:
                path = step.__module__
            logger.debug("class: %s | path: %s", class_name, path)
            chain_spec.append(
                {SPEC_CLASS: class_name, SPEC_PATH: path, SPEC_SPEC: step.dict()}
            )
        chain_dict = {
            SPEC_CHAIN_TYPE: self.CHAIN_TYPE,
            SPEC_CHAIN: chain_spec,
        }

        if filename:
            self._save_to_file(chain_dict, filename, overwrite)

        return chain_dict

    def __str__(self) -> str:
        return "\n".join([str(step.__class__) for step in self.steps])

    @staticmethod
    def _load_class_from_file(module_name, file_path, class_name):
        module_spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_name] = module
        module_spec.loader.exec_module(module)
        return getattr(module, class_name)

    @staticmethod
    def _load_class_from_module(module_name, class_name):
        component_module = importlib.import_module(module_name)
        return getattr(component_module, class_name)

    @staticmethod
    def load_step(config: dict):
        spec = deepcopy(config.get(SPEC_SPEC, {}))
        spec: dict
        class_name = config[SPEC_CLASS]
        module_name = config.get(SPEC_PATH)

        if not module_name and "." in class_name:
            # The class name is given as a.b.c.MyClass
            module_name, class_name = class_name.rsplit(".", 1)

        # Load the step with LangChain loader if it matches the "_type".
        # Note that some LangChain objects are saved with the "_type" but there is no matching loader.
        if (
            str(module_name).startswith("langchain.")
            and SPEC_CHAIN_TYPE in spec
            and spec[SPEC_CHAIN_TYPE] in type_to_loader_dict
        ):
            return load_chain_from_config(spec)

        # Load the guardrail using spec as kwargs
        if hasattr(guardrails, class_name):
            # Built-in guardrail, including custom huggingface guardrail
            component_class = getattr(guardrails, class_name)
            # Copy the path into spec if it is not already there
            if SPEC_PATH in config and SPEC_PATH not in spec:
                spec[SPEC_PATH] = config[SPEC_PATH]
        elif SPEC_PATH in config:
            # Custom component
            # For custom guardrail, the module name could be a file.
            if "://" in module_name:
                # TODO: Load module from OCI object storage
                #
                # component_class = GuardrailSequence._load_class_from_file(
                #     module_name, temp_file, class_name
                # )
                raise NotImplementedError(
                    f"Loading module from {module_name} is not supported."
                )
            elif os.path.exists(module_name):
                component_class = GuardrailSequence._load_class_from_file(
                    module_name, module_name, class_name
                )
            else:
                component_class = GuardrailSequence._load_class_from_module(
                    module_name, class_name
                )
        elif "." in class_name:
            # The class name is given as a.b.c.MyClass
            module_name, class_name = class_name.rsplit(".", 1)
            component_class = GuardrailSequence._load_class_from_module(
                module_name, class_name
            )
        else:
            raise ValueError(f"Invalid Guardrail: {class_name}")

        spec.pop(SPEC_CHAIN_TYPE, None)
        return component_class(**spec)

    @classmethod
    def load(cls, chain_dict: dict) -> "GuardrailSequence":
        """Loads the sequence from a dictionary config.

        Parameters
        ----------
        chain_dict : dict
            A dictionary containing the key "chain".
            The value of "chain" should be a list of dictionary.
            Each dictionary corresponds to a step in the chain.

        Returns
        -------
        GuardrailSequence
            A GuardrailSequence loaded from the config.
        """
        chain_spec = chain_dict[SPEC_CHAIN]
        chain = cls()
        for config in chain_spec:
            guardrail = cls.load_step(config)
            # Chain the guardrail
            chain |= guardrail
        return chain

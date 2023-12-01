import unittest
from langchain.load.serializable import Serializable
from langchain.schema.embeddings import Embeddings

from langchain.vectorstores import OpenSearchVectorSearch, FAISS


import unittest
from ads.llm.serialize import OpenSearchVectorDBSerializer, FaissSerializer, RetrievalQASerializer
from tests.unitary.with_extras.langchain.test_guardrails import FakeLLM
import os
from unittest import mock
from typing import Any, Dict, List, Mapping, Optional
from langchain.chains import RetrievalQA
from langchain import llms
from langchain.llms import loading




class FakeEmbeddings(Serializable, Embeddings):
    """Fake LLM for testing purpose."""

    @property
    def _llm_type(self) -> str:
        return "custom_embeddings"

    @classmethod
    def is_lc_serializable(cls) -> bool:
        """This class can be serialized with default LangChain serialization."""
        return True

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[1] * 1024 for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return [1] * 1024
    
    
class TestOpensearchSearchVectorSerializers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env_patcher = mock.patch.dict(os.environ, {"oci_opensearch_username": "username",
                                                    "oci_opensearch_password": "password",
                                                    "oci_opensearch_verify_certs": "True",
                                                    "oci_opensearch_ca_certs": "/path/to/cert.pem"})
        cls.env_patcher.start()
        cls.index_name = "test_index"
        cls.embeddings = FakeEmbeddings()
        cls.opensearch = OpenSearchVectorSearch(
            "https://localhost:8888",
            embedding_function=cls.embeddings,
            index_name=cls.index_name,
            engine="lucene",
            http_auth=(os.environ["oci_opensearch_username"], os.environ["oci_opensearch_password"]),
            verify_certs=os.environ["oci_opensearch_verify_certs"],
            ca_certs=os.environ["oci_opensearch_ca_certs"],
        )
        cls.serializer = OpenSearchVectorDBSerializer()
        super().setUpClass()

    def test_type(self):
        # Test type()
        self.assertEqual(self.serializer.type(), "OpenSearchVectorSearch")

    def test_save(self):
        serialized = self.serializer.save(self.opensearch)
        assert serialized["id"] == ['langchain', 'vectorstores', 'opensearch_vector_search', 'OpenSearchVectorSearch']
        assert serialized["kwargs"]["opensearch_url"] == "https://localhost:8888"
        assert serialized["kwargs"]["engine"] == "lucene"
        assert serialized["_type"] == "OpenSearchVectorSearch"

    def test_load(self):
        serialized = self.serializer.save(self.opensearch)
        new_opensearch = self.serializer.load(serialized, valid_namespaces=["tests"])
        assert isinstance(new_opensearch, OpenSearchVectorSearch)


class TestFAISSSerializers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.embeddings = FakeEmbeddings()
        text_embedding_pair = [("test", [1] * 1024)]
        cls.db = FAISS.from_embeddings(text_embedding_pair, cls.embeddings)
        cls.serializer = FaissSerializer()
        super().setUpClass()

    def test_type(self):
        self.assertEqual(self.serializer.type(), "FAISS")

    def test_save(self):
        serialized = self.serializer.save(self.db)
        assert serialized["embedding_function"]["id"] == ["tests", "unitary", "with_extras", "langchain", "test_serializers", "FakeEmbeddings"]
        assert isinstance(serialized["vectordb"], str)

    def test_load(self):
        serialized = self.serializer.save(self.db)
        new_db = self.serializer.load(serialized, valid_namespaces=["tests"])
        assert isinstance(new_db, FAISS)


class TestRetrievalQASerializer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create a sample RetrieverQA object for testing
        cls.llm = FakeLLM()
        cls.embeddings = FakeEmbeddings()
        text_embedding_pair = [("test", [1] * 1024)]
        cls.db = FAISS.from_embeddings(text_embedding_pair, cls.embeddings)
        cls.serializer = FaissSerializer()
        cls.retriever = cls.db.as_retriever()
        cls.qa = RetrievalQA.from_chain_type(llm=cls.llm,
                                            chain_type="stuff",
                                            retriever=cls.retriever)
        cls.serializer = RetrievalQASerializer()
        from copy import deepcopy
        cls.original_type_to_cls_dict = deepcopy(llms.get_type_to_cls_dict())
        __lc_llm_dict = llms.get_type_to_cls_dict()
        __lc_llm_dict["custom_embedding"] = lambda: FakeEmbeddings
        __lc_llm_dict["custom"] = lambda: FakeLLM

        def __new_type_to_cls_dict():
            return __lc_llm_dict

        llms.get_type_to_cls_dict = __new_type_to_cls_dict
        loading.get_type_to_cls_dict = __new_type_to_cls_dict

    def test_type(self):
        self.assertEqual(self.serializer.type(), "retrieval_qa")

    def test_save(self):
        # Serialize the RetrieverQA object
        serialized = self.serializer.save(self.qa)

        # Ensure that the serialized object is a dictionary
        self.assertIsInstance(serialized, dict)

        # Ensure that the serialized object contains the necessary keys
        self.assertIn("combine_documents_chain", serialized)
        self.assertIn("retriever_kwargs", serialized)
        serialized["vectordb"]["class"] == "FAISS"

    def test_load(self):
        # Create a sample config dictionary
        serialized = self.serializer.save(self.qa)

        # Deserialize the serialized object
        deserialized = self.serializer.load(serialized, valid_namespaces=["tests"])

        # Ensure that the deserialized object is an instance of RetrieverQA
        self.assertIsInstance(deserialized, RetrievalQA)

    @classmethod
    def tearDownClass(cls) -> None:
        llms.get_type_to_cls_dict = cls.original_type_to_cls_dict
        loading.get_type_to_cls_dict = cls.original_type_to_cls_dict
        return super().tearDownClass()


if __name__ == "__main__":
    unittest.main()
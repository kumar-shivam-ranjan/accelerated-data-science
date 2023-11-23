from elasticsearch import Elasticsearch


class ElasticSearchClientConfig:
    def __init__(self, host, username, password, scheme="https", verify_certs=True):
        """
        Initialize the Elasticsearch client configuration.

        Parameters:
            - hosts (str or list): The Elasticsearch server address. Can be a single string or a list of strings.
            - username (str): The Elasticsearch username for authentication.
            - password (str): The Elasticsearch password for authentication.
            - scheme (str): The scheme used for connecting to Elasticsearch ('http' or 'https').
            - verify_certs (bool): Whether to verify SSL certificates.

        Example:
            config = ElasticSearchClientConfig(hosts='localhost', username='elastic', password='your_password')
            es = config.get_client()
        """
        self.host = host
        self.username = username
        self.password = password
        self.scheme = scheme
        self.verify_certs = verify_certs

    def get_client(self):
        """
        Get an instance of the Elasticsearch client configured based on the provided parameters.

        Returns:
            Elasticsearch: An instance of the Elasticsearch client.
        """
        return Elasticsearch(
            hosts=f"{self.scheme}://{self.host}:9200",
            basic_auth=(self.username, self.password),
            verify_certs=self.verify_certs,
            ssl_show_warn=False,
        )

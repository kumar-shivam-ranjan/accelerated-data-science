import redis

class RedisClientConfig:
    def __init__(self, host='localhost', port=6379, password=None, db=0):
        """
        Initialize the Redis client configuration.

        Parameters:
            - host (str): The Redis server address.
            - port (int): The Redis server port.
            - password (str): The Redis password for authentication.
            - db (int): The Redis database index.

        Example:
            config = RedisClientConfig(host='localhost', port=6379, password='your_password')
            redis_client = config.get_client()
        """
        self.host = host
        self.port = port
        self.password = password
        self.db = db

    def get_client(self):
        """
        Get an instance of the Redis client configured based on the provided parameters.

        Returns:
            Redis: An instance of the Redis client.
        """
        return redis.StrictRedis(
            host=self.host,
            port=self.port,
            password=self.password,
            db=self.db,
            decode_responses=True  # Decodes responses from bytes to strings
        )
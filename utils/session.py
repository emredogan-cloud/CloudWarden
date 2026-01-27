import boto3
from typing import TYPE_CHECKING, overload, Literal

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_cloudwatch import CloudWatchClient
    from mypy_boto3_dynamodb import DynamoDBClient
AWS_service = Literal['ec2' , 'dynamodb' , 'cloudwatch']

class AWSSessionManager:
    _instance = None
    
    def __init__(self):
        self._session = {}

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_session(self, region: str = "us-east-1") -> boto3.Session:
        if region not in self._session:
            self._session[region] = boto3.Session(region_name=region)
        return self._session[region]

    
    @overload
    def get_client(self, service_name: Literal['ec2'], region: str = "us-east-1") -> "EC2Client": ...

    @overload
    def get_client(self, service_name: Literal['cloudwatch'], region: str = "us-east-1") -> "CloudWatchClient": ...

    @overload
    def get_client(self, service_name: Literal['dynamodb'], region: str = "us-east-1") -> "DynamoDBClient": ...


    def get_client(self, service_name: AWS_service, region: str = "us-east-1"):
        session = self.get_session(region)
        return session.client(service_name)
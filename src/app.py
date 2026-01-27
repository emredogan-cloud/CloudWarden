from utils.logging import get_logger
from utils.session import AWSSessionManager
from botocore.exceptions import ClientError
from datetime import datetime, timedelta, timezone
import os
import urllib3
import json
from typing import List,Dict
from mypy_boto3_ec2.type_defs import FilterTypeDef


manager = AWSSessionManager.get_instance()
logger = get_logger('Warden' , 'DEBUG')


def lambda_handler(event, context):
    ec2 = manager.get_client('ec2')
    cloudwatch = manager.get_client('cloudwatch')
    dynamodb = manager.get_client('dynamodb')

    tag_key = os.environ.get('TARGET_TAG_KEY', 'Env')
    tag_value = os.environ.get('TARGET_TAG_VALUE', 'Dev')
    table_name = os.environ.get('DYNAMO_TABLE')
    if not table_name:
        raise RuntimeError('table_name is not set')

    logger.info(f'Bot is Starting... Targets: {tag_key} : {tag_value}')

    instance_count = 0
    checked_instance_ids = []


    def send_slack_alert(message):
        try:
            slack_token = os.environ.get('SLACK_WEBHOOK_URL')

            if not slack_token:
                raise RuntimeError('slack_token is not set')
            http = urllib3.PoolManager()

            full_message = f" *AWS ALERT* \n{message}\n\n_cc: Emre - Cloud Engineer_"

            http.request(
                'POST',
                slack_token,
                body=json.dumps({'text': full_message}),
                headers={'Content-Type':'application/json'}
            )
        except ClientError as e:
            error = e.response['Error']['Code']
            messages = e.response['Error']['Message']
            logger.warning(f'ERROR: {error} | {messages}')

    try:
        paginator = ec2.get_paginator('describe_instances')

        filters : List[FilterTypeDef] = [
            {'Name': f'tag:{tag_key}', 'Values': [tag_value]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]

        page_iterator = paginator.paginate(Filters=filters)

        for page in page_iterator:
            for reservations in page.get('Reservations', []):
                for instance in reservations.get('Instances', []):
                    instance_count += 1
                    instance_id = instance['InstanceId']
                    checked_instance_ids.append(instance_id)

                    logger.info(f'InstanceId : {instance_id}')

                    end_time = datetime.now(timezone.utc)
                    start_time = end_time - timedelta(hours=1)

                    response = cloudwatch.get_metric_statistics(
                        Namespace='AWS/EC2',
                        MetricName='CPUUtilization',
                        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
                        StartTime=start_time,
                        EndTime=end_time,
                        Period=3600,
                        Statistics=['Average'],
                        Unit='Percent'
                    )

                    datapoints = response.get('Datapoints', [])

                    if not datapoints:
                        logger.warning(f"InstanceID : {instance_id} No Data Found")
                        continue

                    datapoints.sort(key=lambda x: x['Timestamp'])
                    latest = datapoints[-1]

                    logger.info(f"Last datapoint (1-hours avg) CPU {latest["Average"]:.2f}%")

                    if latest['Average'] < 10.00:
                        logger.warning(f"InstanceID : {instance_id} CPU Usage is Very low : {latest["Average"]:.2f}%")
                        send_slack_alert(f'InstanceId: {instance_id} CPU usage {latest['Average']:.2f} IS Very Low "{instance_id} SERVER İS STOPPİNG!!!". ')
                        logger.info(f'Server is Stopping... ID: {instance_id}')
                        ec2.stop_instances(InstanceIds=[instance_id])
                        dynamodb.put_item(
                            TableName=table_name,
                            Item={
                                'InstanceId':{'S': instance_id},
                                'ActionTime':{'S': str(timezone.utc)},
                                'ActionType':{'S': 'AUTO_STOP'},
                                'Reason':{'S':f'CPU is Low {latest["Average"]}%'}
                            }
                        )
                        CPU_value = latest['Average']
                        logger.info('The data is being written to the table.')
                    elif latest['Average'] > 80.00:
                        logger.warning(f"InstanceID : {instance_id} CPU Usage is Very HIGH : {CPU_value}%")
                        send_slack_alert(f'InstanceId: {instance_id} CPU USAGE: {latest["Average"]} is Very HİGH!!! Please Checked')
                    else:
                        logger.info(f'InstanceID : {instance_id} CPU Usage is Normal : {CPU_value}%')

        return {
            "status": "success",
            "checked_instances": instance_count,
            "instance_ids": checked_instance_ids
        }

    except ClientError as e:
        error = e.response['Error']['Code']
        message = e.response['Error']['Message']
        logger.error(f'AWS ERROR | {error} | {message}')

        return {
            "status": "error",
            "aws_error": error,
            "message": message
        }




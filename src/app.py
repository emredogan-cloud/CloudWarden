import boto3
from botocore.exceptions import ClientError
import logging
from datetime import datetime, timedelta, timezone
import os
import urllib3
import json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def lambda_handler(event, context):
    ec2 = boto3.client('ec2')
    cloudwatch = boto3.client('cloudwatch')
    dynamodb = boto3.client('dynamodb')

    tag_key = os.environ.get('TARGET_TAG_KEY', 'Env')
    tag_value = os.environ.get('TARGET_TAG_VALUE', 'Dev')
    table_name = os.environ.get('DYNAMO_TABLE')
    if not table_name:
        raise RuntimeError('table_name is not set')

    logging.info(f'Bot is Starting... Targets: {tag_key} : {tag_value}')

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
            logging.warning(f'ERROR: {error} | {messages}')

    try:
        paginator = ec2.get_paginator('describe_instances')

        filters = [
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

                    logging.info(f'InstanceId : {instance_id}')

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
                        logging.warning(f"InstanceID : {instance_id} No Data Found")
                        continue

                    datapoints.sort(key=lambda x: x['Timestamp'])
                    latest = datapoints[-1]

                    logging.info(f'Last datapoint (1-hours avg) CPU {latest["Average"]:.2f}%')

                    if latest['Average'] < 10.00:
                        logging.warning(f'InstanceID : {instance_id} CPU Usage is Very low : {latest["Average"]:.2f}%')
                        logging.info(f'Server is Stopping... ID: {instance_id}')
                        ec2.stop_instances(InstanceIds=[instance_id])
                        dynamodb.put_item(
                            TableName=table_name,
                            Item={
                                'InstanceId':{'S': instance_id},
                                'ActionTime':{'S': str(datetime.now())},
                                'ActionType':{'S': 'AUTO_STOP'},
                                'Reason':{'S':f'CPU is Low {latest["Average"]}%'}
                            }
                        )
                        logging.info('The data is being written to the table.')
                    elif latest['Average'] > 80.00:
                        logging.warning(f'InstanceID : {instance_id} CPU Usage is Very HIGH : {latest["Average"]:.2f}%')
                        send_slack_alert(f'InstanceId: {instance_id} CPU USAGE: {latest["Average"]} is Very HİGH!!! Please Checked')
                    else:
                        logging.info(f'InstanceID : {instance_id} CPU Usage is Normal : {latest["Average"]:.2f}%')

        return {
            "status": "success",
            "checked_instances": instance_count,
            "instance_ids": checked_instance_ids
        }

    except ClientError as e:
        error = e.response['Error']['Code']
        message = e.response['Error']['Message']
        logging.error(f'AWS ERROR | {error} | {message}')

        return {
            "status": "error",
            "aws_error": error,
            "message": message
        }




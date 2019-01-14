# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Licensed under the MIT No Attribution aka MIT-Zero (https://github.com/aws/mit-0) license

import json
import boto3
import botocore
import random
import time
import os

events_client = boto3.client('events')
cloudwatch = boto3.client('cloudwatch')
lambda_client = boto3.client('lambda')
dms_client = boto3.client('dms')
sns = boto3.client('sns')
s3_client = boto3.resource('s3')

def get_replication_instance_details(replication_instance_name):
    """Returns instance details given instance name """
    
    # Get all the replication instances list. We can add filters to simplify code, to improve this piece
    all_replication_instances = dms_client.describe_replication_instances(
    #     Filters=[
    #     {
    #         'Name': 'replication-instance-id',
    #         'Values': [replication_instance_name]
    #     }
    # ]
    )

    for instance in all_replication_instances['ReplicationInstances']:
        if instance['ReplicationInstanceIdentifier'] == replication_instance_name:
             # Get details of our instance
            return instance
    return ''

# Send notification for successful/failed instance modification operation
def send_sns(subject, message):
    """Sends message to a SNS. This is primarily for notifying status of 
    instance modification operation at various stages"""

    topicArn = ''
    
    try:
        topicArn = os.environ['TOPIC_ARN']
        response = sns.publish(
            TopicArn=topicArn,
            Subject=subject,
            Message=message
        )

        return response
    except:
        return   
    

def get_replication_tasks(replication_instance_arn):
    """Returns the ist of replication tasks"""
    existing_tasks = []
    dms_client = boto3.client('dms')
    replication_tasks = dms_client.describe_replication_tasks()
    for task in replication_tasks['ReplicationTasks']:
        if task['ReplicationInstanceArn'] == replication_instance_arn:
            existing_tasks.append(task)
    return existing_tasks


def create_cloudwatch_event(event, context, replication_instance_details, replication_tasks):
    """Creates a scheduled cloudwatch event to temporarily poll instance after modification request 
    has been initiated. This scheduled event will initiate this very same lambda function
    every 1 minute to deal with maximum execution time limit of 5 minutes for lambda. Nice trick :-)
    """
    
    print('inside create_cloudwatch_event')
    
    self_arn = context.invoked_function_arn # get arn of this lambda function
    replication_instance_name = event['Trigger']['Dimensions'][0]['value']
    rule_response = events_client.put_rule(
        Name="dms-scheduled-event-" + replication_instance_name,
        ScheduleExpression="rate(1 minute)",
        State='ENABLED',
    )

    # set resource policy (start trusting cloudwatch to invoke lambda) for lambda 
    # so as to be able to invoke lambda by cloudwatch event
    lambda_client.add_permission(
        FunctionName=self_arn,
        StatementId=str(random.getrandbits(32)),
        Action='lambda:InvokeFunction',
        Principal='events.amazonaws.com',
        SourceArn=rule_response['RuleArn']
    )
 
    # Create that that we will store in scheduled event for persisting through the entire instance modification process
    target_input = {
        "replication_instance": replication_instance_name,
        "alarm_name": event["AlarmName"],
        "existing_tasks": replication_tasks,
        "start_time": time.time()   # store the start time of instance modification. Will use this for timeout calculation
    }
    
    print('target_input: ', target_input)

    # put the lambda as target for scheduled cloudwatch event
    events_client.put_targets(
        Rule="dms-scheduled-event-" + replication_instance_name,
        Targets=[
            {
                'Id': "1",  # we will use this ID during deletion of this target later as well
                'Arn': self_arn,
                'Input': json.dumps(target_input)
            }
        ]
    )

def delete_cloudwatch_event(event):
    """Deletes the scheduled cloudwatch event. """
    rule_name = 'dms-scheduled-event-' + event['replication_instance']
    print('Inside delete_cloudwatch_event. Attempting to delete: ', rule_name)
    
    # delete the target first. Without this rule deletion will silently fail
    response = events_client.remove_targets(
        Rule = rule_name,
        Ids = ['1']
    )
    
    # now delete the rule
    response = events_client.delete_rule(
        Name=rule_name
    )
    
    print('Response to delete cloudwatch scheduled event: ', rule_name , ' is: ', response)


def get_next_instance_class(existing_instance_class, scale_type):
    """Return the next higher/lower instance type to which the instance will be modified.
    scale_type: cpu_high, cpu_low, memory_high, memory_low
    """

    ######### Get the json resource file from bucket ##########
    BUCKET_NAME = ""
    try:
        BUCKET_NAME = os.environ['BUCKET_NAME']
    except:
        BUCKET_NAME = 'aws-database-blog'  # bucket that holds the json file
    
    KEY_NAME = ""
    try:
        KEY_NAME = os.environ['KEY_NAME']
    except:
        KEY_NAME = 'artifacts/auto_scale_DMS_replication_instance/instance_types.json'  # name of the json file
    
    obj = s3_client.Object(BUCKET_NAME, KEY_NAME)
    
    instance_types = json.loads(obj.get()['Body'].read().decode('utf-8'))
    file_path = 's3://' + BUCKET_NAME + '/' + KEY_NAME
    ######### Got the json resource file from bucket ##########

    ## If autoscaling up or down is disabled in json resource file then quit ###
    autoscaling_up_enabled = instance_types['autoscaling_up_enabled']
    autoscaling_down_enabled = instance_types['autoscaling_down_enabled']

    if (scale_type == 'cpu_high' or scale_type == 'memory_high') and autoscaling_up_enabled == 'false':
        print('Autoscaling UP is disabled in:' + file_path + '. Quitting now.. Bye!!!')
        return
    elif (scale_type == 'cpu_low' or scale_type == 'memory_low') and autoscaling_down_enabled == 'false':
        print('Autoscaling DOWN is disabled in:' + file_path + '. Quitting now.. Bye!!!')
        return
    ###### resource file autoscaling configration check complete ######

    next_instance_type = instance_types[existing_instance_class][scale_type]
    
    print('existing_instance_type: ', existing_instance_class, ', next_instance_type: ', next_instance_type)

    if next_instance_type == 'no_action':
        print('Not taking action for :', existing_instance_class, ' for :', scale_type , ' as defined in: ', file_path)
        return 'no_action'    
    return next_instance_type

def poll_instance(replication_instance_name):
    """ Poll instance to see if it has become available again after modification request"""
    print('Polling instance for resize completion... for: ', replication_instance_name)
    instance_details = get_replication_instance_details(replication_instance_name)
    if instance_details['ReplicationInstanceStatus'] == "available":
        print('Instance modification completed. Will check status of tasks now.')
        return 0    # success
    return 1    # still waiting


def poll_tasks(existing_tasks, replication_instance_arn):
    print('poll_tasks::existing_tasks: ', existing_tasks)
    """ Poll tasks to see if they come to the same state in which they were before instance modification started"""
    updated_tasks = shorten_replication_tasks(get_replication_tasks(replication_instance_arn))
    print('poll_tasks::updated_tasks: ', updated_tasks)
    for task in existing_tasks:
        for updated_task in updated_tasks:
            if task["ReplicationTaskArn"] == updated_task["ReplicationTaskArn"]:
                if task["Status"] != updated_task["Status"]:
                    return 1    # still waiting
                else:
                    print('task regained its status: ', task["ReplicationTaskArn"])

    print('All tasks are now in same state as they were before instance resize. We are good...')
    return 0    # success


def dms_event_handler(event, context):
    """ Handle the event if the lambda function is triggered by DMS alarm (via SNS topic) """
    # Get our replication instance name
    replication_instance_name = event['Trigger']['Dimensions'][0]['value']

    alarm_name = event['AlarmName']

    # Get existing instance details
    replication_instance_details = get_replication_instance_details(
        replication_instance_name)

    # Get arn and existing class of the instance that we would need for modification
    replication_instance_arn = replication_instance_details['ReplicationInstanceArn']
    replication_instance_class = replication_instance_details['ReplicationInstanceClass']
    replication_instance_status = replication_instance_details['ReplicationInstanceStatus']

    # if for whatever reason instance is not in available statet then quit.
    if replication_instance_status != 'available':
        print('Instance status must be available to make changes to it. Current status of instance: ',
              replication_instance_details['ReplicationInstanceIdentifier'], ' is: ', replication_instance_status)
        return 0

    # get scale type cpu-high/cpu-low. e.g. dms-cpu-high
    event_type = alarm_name[4:len(alarm_name)]  # form dms-cpu-high it returns cpu-high

    # Get the next higher instance class
    next_instance_type = get_next_instance_class(replication_instance_class, event_type)

    if next_instance_type == 'no_action':  # next_instance_type will be no_action if up/down scaling is not possible
        print('Cannot up/down scale as per config file in S3')
        return 0
    
    replication_tasks = shorten_replication_tasks(get_replication_tasks(replication_instance_arn))
    
    # Upgrade/Downgrade the instance to next higher/lower instance class
    dms_client.modify_replication_instance(
        ReplicationInstanceArn=replication_instance_arn,
        ApplyImmediately=True,
        ReplicationInstanceClass=next_instance_type
    )

    send_sns("Instance modification started: " + replication_instance_name, 
    "Instance modification started: " + replication_instance_name)
    
    print('replication_tasks: ', replication_tasks)

    # Now create a cloudwatch event that will hit the lambda every 1 minute to poll for instance and tasks status.
    create_cloudwatch_event(event, context, replication_instance_details, replication_tasks)

def shorten_replication_tasks(replication_tasks):
    """Returns only relevent fields form replication_tasks object """
    tasks = []
    for task in replication_tasks:
        t1 = {
            "ReplicationTaskIdentifier": task['ReplicationTaskIdentifier'],
            "Status": task['Status'],
            "ReplicationTaskArn": task['ReplicationTaskArn']
        }
        tasks.append(t1)
    
    return tasks      

def scheduled_event_handler(event):
    print('scheduled event is: ', event)
    """ Handle the scheduled event. Primary purpose of this method is:
    1. Poll the instance status to see if it has become available again.\n 
    2. Check the status of already running tasks is same after modification. 
     """
    replication_instance_name = event['replication_instance']

    # Get existing instance details
    replication_instance_details = get_replication_instance_details(replication_instance_name)

    # Get arn and existing class of the instance that we would need for modification
    replication_instance_arn = replication_instance_details['ReplicationInstanceArn']

    # get details of the existing replication tasks
    existing_tasks = event['existing_tasks']

    instance_poll_update_status = poll_instance(replication_instance_name)

    if instance_poll_update_status == 1:
        print("Still waiting for instance upgrade/downgrade: ", replication_instance_name, " to complete")
        return 0
    elif instance_poll_update_status == 0:
        print('polling tasks now')
        task_poll_status = poll_tasks(existing_tasks, replication_instance_arn)

    if task_poll_status == 1:
        print("Still waiting for tasks to start")
    elif task_poll_status == 0:
        print('############# Polling tasks also complete. All done ###############')
        # initiate cleanup
        
        # set alarm status to OK so that it can trigger again
        cloudwatch.set_alarm_state(AlarmName=event["alarm_name"], 
            StateValue="OK", 
            StateReason="resetting so that it can get triggered again later.")
        
        # delete the scheduled event so it stops triggering lambda again and again
        delete_cloudwatch_event(event)
        send_sns("Instance modification completed: " + replication_instance_name, "DMS Instance upgrade/downgrade successful: " + replication_instance_name)
    
    modification_timeout = 0
    
    try:
        # get the MODIFICATION_TIMEOUT value from env variable if available
        modification_timeout = os.environ['MODIFICATION_TIMEOUT']
        modification_timeout = int(modification_timeout)
    except:
        # else use a default value for MODIFICATION_TIMEOUT
        modification_timeout = 1200 # default 20 minutes
        
    current_time = time.time()
    start_time = event["start_time"]

    if current_time - start_time > modification_timeout:
        print("Instance upgrade/downgrade timed out. Timeout was: ", modification_timeout, ' seconds')
        delete_cloudwatch_event(event)
        send_sns("DMS Instance upgrade/downgrade timed out for: " + replication_instance_name, "DMS Instance upgrade/downgrade timed out for: " + replication_instance_name)

def lambda_handler(event, context):
    # Find the type of event scheduled or dms
    dms_alarms = ['dms_cpu_high', 'dms_cpu_low', 'dms_memory_high', 'dms_memory_low']
    
    message = ''
    
    try:
        # if event is from SNS then we need to convert the message from text to json
        message = json.loads(event["Records"][0]["Sns"]["Message"])
    except:
        # if message is not from SNS then its from scheduled cloudwatch event and we process it directly
        message = event
    
    if "replication_instance" in message:
        print("------cloudwatch scheduled event------")
        scheduled_event_handler(message)
    elif message["AlarmName"] in dms_alarms:
        print("------dms event: ", message["AlarmName"] ," -------")
        dms_event_handler(message, context)

    return 0


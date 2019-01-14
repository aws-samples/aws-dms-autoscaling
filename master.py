# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Licensed under the MIT No Attribution aka MIT-Zero (https://github.com/aws/mit-0) license

import dms
import json
import boto3

f = open("event-cpu-low.json", "rb")
# f = open("cloudwatch-scheduled-event.json", "rb")
data = f.read().decode('utf-8')
f.close()

boto3.setup_default_session(profile_name='ballu')

# print(type(data))

# print(data['Records'][0]['Sns']['Message'])

dms.lambda_handler(data,1)

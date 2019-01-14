# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Licensed under the MIT No Attribution aka MIT-Zero (https://github.com/aws/mit-0) license

import dms
import unittest
import warnings
import boto3
from unittest.mock import MagicMock

class TestDMSMethods(unittest.TestCase):
    
    def test_poll_tasks(self):
        warnings.simplefilter('ignore', ResourceWarning)
        print('Testing poll_tasks')

        repl_instance_arn = "arn:aws:dms:us-west-2:365610231659:rep:AS6TUTJLSSLMGWLPH3XJ6BPUPU"

        replication_tasks = dms.get_replication_tasks(repl_instance_arn)

        dms.get_replication_tasks = MagicMock(return_value=replication_tasks)

        poll_tasks_status = dms.poll_tasks(replication_tasks, repl_instance_arn)

        self.assertEqual(poll_tasks_status, 0)

if __name__ == '__main__':
    unittest.main()
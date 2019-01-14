# Copyright 2016 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# Licensed under the MIT No Attribution aka MIT-Zero (https://github.com/aws/mit-0) license

import dms
import unittest
import warnings

class TestDMSMethods(unittest.TestCase):
    
    def test_get_next_instance_class_high(self):
        warnings.simplefilter('ignore', ResourceWarning)
        print('Testing if we can move one instance high')
        existing_instance_class = "dms.c4.2xlarge"
        self.assertEqual(dms.get_next_instance_class(existing_instance_class, 'cpu_high'), "dms.c4.4xlarge")
    
    def test_get_next_instance_class_highest(self):
        warnings.simplefilter('ignore', ResourceWarning)
        print('Testing if we return 0 if we are already on highest level and trying to scale up')
        existing_instance_class = "dms.r4.8xlarge"
        self.assertEqual(dms.get_next_instance_class(existing_instance_class, 'cpu_high'), 'no_action')
    
    def test_get_next_instance_class_low(self):
        warnings.simplefilter('ignore', ResourceWarning)
        print('Testing if we can move one instance low')
        existing_instance_class = "dms.c4.4xlarge"
        self.assertEqual(dms.get_next_instance_class(existing_instance_class, 'cpu_low'), "dms.c4.2xlarge")
    
    def test_get_next_instance_class_lowest(self):
        warnings.simplefilter('ignore', ResourceWarning)
        print('Testing if we return 0 if we are already on lowest level and trying to scale down')
        existing_instance_class = "dms.t2.micro"
        self.assertEqual(dms.get_next_instance_class(existing_instance_class, 'cpu_low'), 'no_action')

if __name__ == '__main__':
    unittest.main()
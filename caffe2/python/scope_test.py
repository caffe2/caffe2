# Copyright (c) 2016-present, Facebook, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##############################################################################

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from caffe2.python import scope, core
from caffe2.proto import caffe2_pb2

import unittest
import threading
import time

SUCCESS_COUNT = 0


def thread_runner(idx, testobj):
    global SUCCESS_COUNT
    testobj.assertEquals(scope.CurrentNameScope(), "")
    testobj.assertEquals(scope.CurrentDeviceScope(), None)
    namescope = "namescope_{}".format(idx)
    dsc = core.DeviceOption(caffe2_pb2.CUDA, idx)
    with scope.DeviceScope(dsc):
        with scope.NameScope(namescope):
            testobj.assertEquals(scope.CurrentNameScope(), namescope + "/")
            testobj.assertEquals(scope.CurrentDeviceScope(), dsc)

            time.sleep(0.01 + idx * 0.01)
            testobj.assertEquals(scope.CurrentNameScope(), namescope + "/")
            testobj.assertEquals(scope.CurrentDeviceScope(), dsc)

    testobj.assertEquals(scope.CurrentNameScope(), "")
    testobj.assertEquals(scope.CurrentDeviceScope(), None)
    SUCCESS_COUNT += 1


class TestScope(unittest.TestCase):

    def testNamescopeBasic(self):
        self.assertEquals(scope.CurrentNameScope(), "")

        with scope.NameScope("test_scope"):
            self.assertEquals(scope.CurrentNameScope(), "test_scope/")

        self.assertEquals(scope.CurrentNameScope(), "")

    def testNamescopeAssertion(self):
        self.assertEquals(scope.CurrentNameScope(), "")

        try:
            with scope.NameScope("test_scope"):
                self.assertEquals(scope.CurrentNameScope(), "test_scope/")
                raise Exception()
        except Exception:
            pass

        self.assertEquals(scope.CurrentNameScope(), "")

    def testDevicescopeBasic(self):
        self.assertEquals(scope.CurrentDeviceScope(), None)

        dsc = core.DeviceOption(caffe2_pb2.CUDA, 9)
        with scope.DeviceScope(dsc):
            self.assertEquals(scope.CurrentDeviceScope(), dsc)

        self.assertEquals(scope.CurrentDeviceScope(), None)

    def testDevicescopeAssertion(self):
        self.assertEquals(scope.CurrentDeviceScope(), None)

        dsc = core.DeviceOption(caffe2_pb2.CUDA, 9)

        try:
            with scope.DeviceScope(dsc):
                self.assertEquals(scope.CurrentDeviceScope(), dsc)
                raise Exception()
        except Exception:
            pass

        self.assertEquals(scope.CurrentDeviceScope(), None)

    def testMultiThreaded(self):
        """
        Test that name/device scope are properly local to the thread
        and don't interfere
        """
        global SUCCESS_COUNT
        self.assertEquals(scope.CurrentNameScope(), "")
        self.assertEquals(scope.CurrentDeviceScope(), None)

        threads = []
        for i in range(4):
            threads.append(threading.Thread(
                target=thread_runner,
                args=(i, self),
            ))
        for t in threads:
            t.start()

        with scope.NameScope("master"):
            self.assertEquals(scope.CurrentDeviceScope(), None)
            self.assertEquals(scope.CurrentNameScope(), "master/")
            for t in threads:
                t.join()

            self.assertEquals(scope.CurrentNameScope(), "master/")
            self.assertEquals(scope.CurrentDeviceScope(), None)

        # Ensure all threads succeeded
        self.assertEquals(SUCCESS_COUNT, 4)

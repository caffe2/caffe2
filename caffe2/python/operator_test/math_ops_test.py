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

from caffe2.python import core
from hypothesis import given
from hypothesis import strategies as st
import caffe2.python.hypothesis_test_util as hu

import numpy as np
import unittest


class TestMathOps(hu.HypothesisTestCase):

    @given(X=hu.tensor(),
           exponent=st.floats(min_value=2.0, max_value=3.0),
           **hu.gcs)
    def test_elementwise_power(self, X, exponent, gc, dc):
        def powf(X):
            return (X ** exponent,)

        def powf_grad(g_out, outputs, fwd_inputs):
            return (exponent * (fwd_inputs[0] ** (exponent - 1)) * g_out,)

        op = core.CreateOperator(
            "Pow", ["X"], ["Y"], exponent=exponent)

        self.assertReferenceChecks(gc, op, [X], powf,
                                   output_to_grad="Y",
                                   grad_reference=powf_grad),

    @given(X=hu.tensor(),
           exponent=st.floats(min_value=-3.0, max_value=3.0),
           **hu.gcs)
    def test_sign(self, X, exponent, gc, dc):
        def signf(X):
            return [np.sign(X)]

        op = core.CreateOperator(
            "Sign", ["X"], ["Y"])

        self.assertReferenceChecks(gc, op, [X], signf),
        self.assertDeviceChecks(dc, op, [X], [0])


if __name__ == "__main__":
    unittest.main()

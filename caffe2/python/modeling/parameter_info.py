from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals
from caffe2.python import core

import numpy as np


class ParameterType(object):
    DENSE = 'dense'
    SPARSE = 'sparse'


class ParameterInfo(object):
    def __init__(
            self, param_id, param, key=None, shape=None, length=None,
            grad=None, blob_copy=None):
        assert isinstance(param, core.BlobReference)
        self.param_id = param_id
        self.name = str(param)
        self.blob = param
        self.key = key
        self.shape = shape
        self.size = None if shape is None else np.prod(shape)
        self.length = max(1, length if length is not None else 1)
        self.grad = grad
        self._cloned_init_net = None
        self.blob_copy = blob_copy

    def grad_type(self):
        # self.grad could be None for model parallelism with parameter server
        if self.grad is None:
            return
        return (
            ParameterType.SPARSE if isinstance(self.grad, core.GradientSlice)
            else ParameterType.DENSE)

    def cloned_init_net(self):
        if not self._cloned_init_net:
            init_net, outputs = self.blob.Net().ClonePartial(
                'param_%d_%s_init' % (self.param_id, self.name),
                inputs=[],
                outputs=[self.blob])
            self._cloned_init_net = (init_net, outputs[0])
        return self._cloned_init_net

    def __str__(self):
        return self.name

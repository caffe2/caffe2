/**
 * Copyright (c) 2016-present, Facebook, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "caffe2/operators/cosine_embedding_criterion_op.h"

#include <algorithm>

#include "caffe2/utils/math.h"

namespace caffe2 {

template <>
bool CosineEmbeddingCriterionOp<CPUContext>::RunOnDevice() {
  auto& S = Input(0);
  auto& Y = Input(1);
  auto* output = Output(0);
  CAFFE_ENFORCE(
      S.size() == Y.size(),
      "The embedding and label should have the same size.");
  output->ResizeLike(S);

  const float* Sdata = S.data<float>();
  const int* Ydata = Y.data<int>();
  float* output_data = output->mutable_data<float>();
  for (int i = 0; i < S.size(); ++i) {
    output_data[i] =
        Ydata[i] == 1 ? (1.f - Sdata[i]) : std::max(0.f, Sdata[i] - margin_);
  }
  return true;
}

template <>
bool CosineEmbeddingCriterionGradientOp<CPUContext>::RunOnDevice() {
  auto& S = Input(0);
  auto& Y = Input(1);
  auto& dOutput = Input(2);
  auto* dS = Output(0);

  dS->ResizeLike(S);

  const float* Sdata = S.data<float>();
  const int* Ydata = Y.data<int>();
  const float* dOutput_data = dOutput.data<float>();
  float* dSdata = dS->mutable_data<float>();
  for (int i = 0; i < S.size(); ++i) {
    dSdata[i] = dOutput_data[i] *
        (Ydata[i] == 1 ? -1.f : static_cast<float>(Sdata[i] >= margin_));
  }
  return true;
}

REGISTER_CPU_OPERATOR(
    CosineEmbeddingCriterion,
    CosineEmbeddingCriterionOp<CPUContext>);
REGISTER_CPU_OPERATOR(
    CosineEmbeddingCriterionGradient,
    CosineEmbeddingCriterionGradientOp<CPUContext>);

OPERATOR_SCHEMA(CosineEmbeddingCriterion)
    .NumInputs(2)
    .NumOutputs(1)
    .SetDoc(R"DOC(
CosineEmbeddingCriterion takes two inputs: the similarity value and
the label, and computes the elementwise criterion output as

  output = 1 - s,               if y == 1
           max(0, s - margin),  if y == -1
)DOC")
    .Input(0, "S", "The cosine similarity as a 1-dim TensorCPU.")
    .Input(1, "Y", "The label as a 1-dim TensorCPU with int value of 1 or -1.")
    .Output(0, "loss", "The output loss with the same dimensionality as S.");

OPERATOR_SCHEMA(CosineEmbeddingCriterionGradient).NumInputs(3).NumOutputs(1);

class GetCosineEmbeddingCriterionGradient : public GradientMakerBase {
  using GradientMakerBase::GradientMakerBase;
  vector<OperatorDef> GetGradientDefs() override {
    return SingleGradientDef(
        "CosineEmbeddingCriterionGradient",
        "",
        vector<string>{I(0), I(1), GO(0)},
        vector<string>{GI(0)});
  }
};
REGISTER_GRADIENT(
    CosineEmbeddingCriterion,
    GetCosineEmbeddingCriterionGradient);

} // namespace caffe2

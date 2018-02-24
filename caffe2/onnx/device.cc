#include "device.h"

#include <cstdlib>
#include <unordered_map>

namespace onnx_caffe2 {
static const std::unordered_map<std::string, DeviceType> kDeviceMap = {
  {"CPU", DeviceType::CPU},
  {"CUDA", DeviceType::CUDA}
};

Device::Device(const std::string &spec) {
  auto pos = spec.find_first_of(':');
  type = kDeviceMap.at(spec.substr(0, pos - 1));
  device_id = atoi(spec.substr(pos + 1).c_str());
}
}



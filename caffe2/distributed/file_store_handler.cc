#include "file_store_handler_op.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

#include <array>
#include <chrono>
#include <iostream>
#include <thread>

#include "caffe2/utils/murmur_hash3.h"

namespace caffe2 {

// Workaround to build file_store_handler in windows. It probably won't run
// correctly, because the functions tmpPath et al. are not cross platform yet.
// TODO(jiayq): if there is a real need, make the file cross platform.
#if defined(_MSC_VER)
static char* realpath(const char* src, char* dst) {
  return strcpy(dst, src);
}
static constexpr int kPathMax = 4096;
#else // defined(_MSC_VER)
static constexpr int kPathMax = PATH_MAX;
#endif // defined(_MSC_VER)

FileStoreHandler::FileStoreHandler(std::string& path) {
  basePath_ = realPath(path);
}

FileStoreHandler::~FileStoreHandler() {}

std::string FileStoreHandler::realPath(const std::string& path) {
  std::array<char, kPathMax> buf;
  CHECK_EQ(buf.data(), realpath(path.c_str(), buf.data())) << "realpath: "
                                                           << strerror(errno);
  return std::string(buf.data());
}

static std::string encodeName(const std::string& name) {
  uint64_t out[2];
  MurmurHash3_x64_128(name.data(), name.size(), 0xcafef00d, &out);
  std::array<char, 32> buf;
  for (int i = 0; i < 16; i++) {
    snprintf(&buf[i * 2], buf.size() - (i * 2), "%02x", ((char*)out)[i]);
  }
  return std::string(buf.data(), buf.size());
}

std::string FileStoreHandler::tmpPath(const std::string& name) {
  return basePath_ + "/." + encodeName(name);
}

std::string FileStoreHandler::objectPath(const std::string& name) {
  return basePath_ + "/" + encodeName(name);
}

void FileStoreHandler::set(const std::string& name, const std::string& data) {
  auto tmp = tmpPath(name);
  auto path = objectPath(name);

  {
    std::ofstream ofs(tmp.c_str(), std::ios::out | std::ios::trunc);
    if (!ofs.is_open()) {
      CAFFE_ENFORCE(
          false, "File cannot be created: ", tmp, " (", ofs.rdstate(), ")");
    }
    ofs << data;
  }

  // Atomically movve result to final location
  auto rv = rename(tmp.c_str(), path.c_str());
  CAFFE_ENFORCE_EQ(rv, 0, "rename: ", strerror(errno));
}

std::string FileStoreHandler::get(const std::string& name) {
  auto path = objectPath(name);
  std::string result;

  // Block until key is set
  wait({name});

  std::ifstream ifs(path.c_str(), std::ios::in);
  if (!ifs) {
    CAFFE_ENFORCE(
        false, "File cannot be opened: ", path, " (", ifs.rdstate(), ")");
  }
  ifs.seekg(0, std::ios::end);
  size_t n = ifs.tellg();
  result.resize(n);
  ifs.seekg(0);
  ifs.read(&result[0], n);
  return result;
}

int64_t FileStoreHandler::add(
    const std::string& /* unused */,
    int64_t /* unused */) {
  CHECK(false) << "add not implemented for FileStoreHandler";
  return 0;
}

bool FileStoreHandler::check(const std::vector<std::string>& names) {
  std::vector<std::string> paths;
  for (const auto& name : names) {
    paths.push_back(objectPath(name));
  }

  for (const auto& path : paths) {
    int fd = open(path.c_str(), O_RDONLY);
    if (fd == -1) {
      // Only deal with files that don't exist.
      // Anything else is a problem.
      CHECK_EQ(errno, ENOENT);

      // One of the paths doesn't exist; return early
      return false;
    }

    close(fd);
  }

  return true;
}

void FileStoreHandler::wait(const std::vector<std::string>& names) {
  // Not using inotify because it doesn't work on many
  // shared filesystems (such as NFS).
  while (!check(names)) {
    /* sleep override */
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
}
}

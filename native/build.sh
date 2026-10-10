#!/usr/bin/env bash
set -euo pipefail
native_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
output=${1:-"$native_dir/libserpantinum-vpn-happ.so"}
"${CXX:-c++}" ${CXXFLAGS:-} -std=c++17 -O2 -fPIC -shared "$native_dir/happ-bridge.cpp" -o "$output" $(pkg-config --cflags --libs Qt6Core Qt6Network) -ldl ${LDFLAGS:-}

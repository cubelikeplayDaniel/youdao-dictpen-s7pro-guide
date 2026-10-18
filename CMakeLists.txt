cmake_minimum_required(VERSION 3.16)
project(s7pro_sdk C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)

# 包含示例程序
add_subdirectory(examples/01_hello_hardware)

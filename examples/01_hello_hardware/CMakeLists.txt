cmake_minimum_required(VERSION 3.16)
project(hello_hardware C)

set(CMAKE_C_STANDARD 99)

add_executable(hello_hardware main.c)

target_compile_options(hello_hardware PRIVATE -Wall -Wextra -O2)

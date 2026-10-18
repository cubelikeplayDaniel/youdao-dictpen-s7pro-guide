# ==============================================================================
# NetEase Youdao Dictionary Pen S7 Pro (Y08_CV1813_V0)
# CMake Cross-Compilation Toolchain Specification
# ==============================================================================

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

# 1. 交叉编译器设置
set(TOOLCHAIN_PREFIX "arm-linux-gnueabihf-")
set(CMAKE_C_COMPILER   "${TOOLCHAIN_PREFIX}gcc")
set(CMAKE_CXX_COMPILER "${TOOLCHAIN_PREFIX}g++")
set(CMAKE_ASM_COMPILER "${TOOLCHAIN_PREFIX}gcc")
set(CMAKE_STRIP        "${TOOLCHAIN_PREFIX}strip")

# 2. Sysroot 目录定位 (优先读取环境变量 S7PRO_SYSROOT，缺省为本地 sysroot)
if(DEFINED ENV{S7PRO_SYSROOT})
    set(CMAKE_SYSROOT "$ENV{S7PRO_SYSROOT}")
else()
    get_filename_component(DEFAULT_SYSROOT "${CMAKE_CURRENT_LIST_DIR}/../sysroot" ABSOLUTE)
    if(EXISTS "${DEFAULT_SYSROOT}")
        set(CMAKE_SYSROOT "${DEFAULT_SYSROOT}")
    endif()
endif()

if(DEFINED CMAKE_SYSROOT)
    message(STATUS "Using S7 Pro Sysroot: ${CMAKE_SYSROOT}")
    set(CMAKE_FIND_ROOT_PATH "${CMAKE_SYSROOT}")
    set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
    set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
    set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
    set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)
endif()

# 3. 针对 Cvitek CV1813 (ARMv7-A Cortex-A7 Hard-Float) 的优化指令集标志
set(TARGET_FLAGS "-march=armv7-a -mtune=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard")

set(CMAKE_C_FLAGS_INIT   "${TARGET_FLAGS} -Wall -Wextra -pthread")
set(CMAKE_CXX_FLAGS_INIT "${TARGET_FLAGS} -Wall -Wextra -pthread")
set(CMAKE_EXE_LINKER_FLAGS_INIT "${TARGET_FLAGS} -Wl,-rpath,/userdata/lib:/userdisk/lib:/oem/lib")

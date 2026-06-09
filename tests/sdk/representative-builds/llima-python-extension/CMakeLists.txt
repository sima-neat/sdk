cmake_minimum_required(VERSION 3.16)

project(representative_llima_python LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(PYTHON_TARGET_VERSION "" CACHE STRING "Target Python major.minor version")
if(PYTHON_TARGET_VERSION STREQUAL "")
  message(FATAL_ERROR "PYTHON_TARGET_VERSION is required")
endif()
if(NOT DEFINED Python_INCLUDE_DIR OR NOT DEFINED Python_LIBRARY)
  message(FATAL_ERROR "Python_INCLUDE_DIR and Python_LIBRARY must point at the target sysroot Python artifacts")
endif()

find_package(Python 3.8 COMPONENTS Interpreter REQUIRED)

add_library(representative_llima_python MODULE module.cpp)
add_library(PythonTarget::Python INTERFACE IMPORTED)
set_target_properties(PythonTarget::Python PROPERTIES
  INTERFACE_INCLUDE_DIRECTORIES "${Python_INCLUDE_DIR}"
  INTERFACE_LINK_LIBRARIES "${Python_LIBRARY}"
)
target_link_libraries(representative_llima_python PRIVATE PythonTarget::Python)
set_target_properties(representative_llima_python PROPERTIES
  PREFIX ""
  SUFFIX ".so"
)

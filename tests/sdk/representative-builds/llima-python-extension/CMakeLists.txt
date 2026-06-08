cmake_minimum_required(VERSION 3.16)

project(representative_llima_python LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(PYTHON_TARGET_VERSION "" CACHE STRING "Target Python major.minor version")
if(PYTHON_TARGET_VERSION STREQUAL "")
  message(FATAL_ERROR "PYTHON_TARGET_VERSION is required")
endif()

find_package(Python ${PYTHON_TARGET_VERSION} EXACT COMPONENTS Interpreter Development REQUIRED)

add_library(representative_llima_python MODULE module.cpp)
target_link_libraries(representative_llima_python PRIVATE Python::Python)
set_target_properties(representative_llima_python PROPERTIES
  PREFIX ""
  SUFFIX ".so"
)
